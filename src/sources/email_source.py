from __future__ import annotations

import email
import html
import imaplib
import logging
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from html.parser import HTMLParser

from .base import Job

log = logging.getLogger(__name__)

# Each job in an Upwork alert email appears as "Job Title: <url with link=title>".
# This captures the title, the canonical job id, and works for both single-job
# alerts and multi-job digests.
JOB_ENTRY_RE = re.compile(
    r"([^\n]{3,250}?)\s*:\s*(https://www\.upwork\.com/jobs/(~0[0-9a-zA-Z]{10,})[^\s]*link=title[^\s]*)"
)
ANY_JOB_ID_RE = re.compile(r"~0[0-9a-zA-Z]{10,}")
BUDGET_RE = re.compile(r"^\s*(Fixed|Hourly)\b[^\n]*", re.I | re.M)
TRAILING_MORE_RE = re.compile(r"\.{0,3}\s*more:\s*https?://\S+", re.I)
URL_RE = re.compile(r"https?://\S+")

# Subjects that are not job alerts at all.
SKIP_SUBJECT_RE = re.compile(
    r"^(invitation to interview|stand out|.*it hasn.t been the same|your proposal"
    r"|congratulations|payment|invoice|weekly summary|security alert)",
    re.I,
)

# Body chrome that must never be mistaken for job description text.
NOISE_RE = re.compile(
    r"(you received this email|manage your alert|view job details|new job alert"
    r"|this job was just posted|^hi\b|^-+$|unsubscribe|freelancer plus|notifications are sent)",
    re.I,
)


class _TextExtractor(HTMLParser):
    """Minimal HTML -> text, stdlib only. Only used when an email has no
    text/plain part; Upwork's alerts normally do."""

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip += 1
        elif tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.parts.append(f": {v} ")
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\xa0]+", " ", raw)
        return raw.strip()


def _body_text(msg: email.message.Message) -> str:
    """Prefer text/plain -- Upwork's alerts carry a clean plaintext part whose
    blank-line structure the parser depends on."""
    plain, html_parts = [], []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            decoded = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        if part.get_content_type() == "text/plain":
            plain.append(decoded)
        elif part.get_content_type() == "text/html":
            html_parts.append(decoded)

    if plain:
        return "\n".join(plain).replace("\r\n", "\n")
    if html_parts:
        p = _TextExtractor()
        p.feed("\n".join(html_parts))
        return p.text().replace("\r\n", "\n")
    return ""


def _tidy(s: str) -> str:
    """Upwork subjects contain HTML entities and stray newlines mid-title."""
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def _extract_details(region: str) -> tuple[str, str, list[str], str]:
    """Pull budget, description, skills and client info out of one job's slice
    of the email."""
    budget = ""
    m = BUDGET_RE.search(region)
    meta = ""
    if m:
        meta = _tidy(m.group(0))
        # "Fixed: $1,500.00 · Est. time: 1 to 3 months · Posted Sun, Aug 23"
        budget = meta.split("·")[0].strip()

    skills: list[str] = []
    client = ""
    desc_parts: list[str] = []

    for block in re.split(r"\n\s*\n", region):
        block = block.strip()
        if not block:
            continue

        if block.lower().startswith("skills:"):
            for line in block.splitlines()[1:]:
                name = line.split(": http")[0].strip()
                if name and len(name) < 60:
                    skills.append(name)
            continue

        if "payment verified" in block.lower() or re.search(r"\d(\.\d)?\s*stars", block, re.I):
            client = _tidy(URL_RE.sub("", block))
            continue

        if meta and block in meta:
            continue
        if NOISE_RE.search(block):
            continue

        # Whatever's left and looks like prose is the description snippet.
        cleaned = TRAILING_MORE_RE.sub("", block)
        cleaned = _tidy(URL_RE.sub("", cleaned))
        if len(cleaned) > 40:
            desc_parts.append(cleaned)

    return budget, " ".join(desc_parts), skills, meta if meta else client


class UpworkEmailSource:
    """Reads Upwork job-alert emails over IMAP and turns them into Job objects.

    This is the free stand-in for the RSS feeds Upwork shut down in Aug 2024.
    Emails are only read, never modified or marked seen -- dedup happens in
    data/seen.json, so this is safe against your real inbox.
    """

    platform = "Upwork"

    def __init__(self, host: str, user: str, password: str, folder: str = "INBOX", lookback_days: int = 2):
        self.host = host
        self.user = user
        self.password = password
        self.folder = folder
        self.lookback_days = lookback_days

    def fetch(self) -> list[Job]:
        if not (self.host and self.user and self.password):
            return []

        try:
            conn = imaplib.IMAP4_SSL(self.host)
            conn.login(self.user, self.password)
            conn.select(self.folder, readonly=True)
        except Exception as e:
            log.error("Upwork email: IMAP login/select failed: %s", e)
            return []

        try:
            since = (datetime.now() - timedelta(days=self.lookback_days)).strftime("%d-%b-%Y")
            status, data = conn.search(None, f'(FROM "upwork.com" SINCE {since})')
            if status != "OK":
                log.warning("Upwork email: IMAP search failed")
                return []

            uids = data[0].split() if data and data[0] else []
            jobs: dict[str, Job] = {}
            skipped = 0

            for uid in uids:
                try:
                    status, msg_data = conn.fetch(uid, "(BODY.PEEK[])")
                    if status != "OK" or not msg_data or not msg_data[0]:
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    subject = _tidy(str(make_header(decode_header(msg.get("Subject", "")))))
                    parsed = self._parse(msg, subject)
                    if not parsed:
                        skipped += 1
                    for job in parsed:
                        jobs[job.id] = job
                except Exception as e:
                    log.warning("Upwork email: skipping unparseable message: %s", e)

            log.info(
                "Upwork email: %d email(s) scanned, %d job(s) found, %d non-job email(s) ignored",
                len(uids),
                len(jobs),
                skipped,
            )
            return list(jobs.values())
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def _parse(self, msg: email.message.Message, subject: str) -> list[Job]:
        if SKIP_SUBJECT_RE.match(subject):
            return []

        text = _body_text(msg)
        if not text or not ANY_JOB_ID_RE.search(text):
            return []

        entries = list(JOB_ENTRY_RE.finditer(text))
        if not entries:
            return []

        jobs: list[Job] = []
        for i, m in enumerate(entries):
            body_title = _tidy(m.group(1))
            job_id = m.group(3)

            # This job's details run until the next job entry (digest emails).
            end = entries[i + 1].start() if i + 1 < len(entries) else len(text)
            region = text[m.end() : end]

            budget, description, skills, meta = _extract_details(region)

            # The subject carries a slightly longer, less-truncated title than the
            # body does -- prefer it when this email is about a single job.
            title = body_title
            if len(entries) == 1 and ":" in subject:
                subject_title = _tidy(subject.split(":", 1)[1])
                if len(subject_title) > len(body_title):
                    title = subject_title
            title = title.rstrip(". ").removesuffix("..").strip()

            full_desc = description
            if skills:
                full_desc += f"\n\nSkills: {', '.join(skills)}"
            if meta:
                full_desc += f"\n\n{meta}"

            jobs.append(
                Job(
                    id=f"upwork:{job_id}",
                    platform=self.platform,
                    title=title[:200] or "Upwork job",
                    url=f"https://www.upwork.com/jobs/{job_id}",
                    description=full_desc.strip()[:4000],
                    budget=budget,
                )
            )

        return jobs
