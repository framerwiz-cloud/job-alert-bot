import logging
import re
from email.utils import formatdate
from xml.sax.saxutils import escape

import requests

from ..config import DATA_DIR
from .base import Job

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.freelancer.com/api/projects/0.1/projects/active"
FEED_FILE = DATA_DIR / "freelancer.xml"

# The API equivalent of this saved search. Edit BASE_PARAMS / QUERIES to change filters.
SAVED_SEARCH_URL = (
    "https://www.freelancer.com/search/projects?types=hourly,fixed"
    "&clientCountries=gb,us,ca,au,de,sa,ae&projectSort=latest&projectLanguages=en"
    "&projectFixedPriceMin=400&projectHourlyRateMin=10&projectSkills=17,69,482,2037,2825"
)
BASE_PARAMS = {
    "jobs[]": [17, 69, 482, 2037, 2825],
    "countries[]": ["gb", "us", "ca", "au", "de", "sa", "ae"],
    "languages[]": ["en"],
    "sort_field": "time_updated",
    "full_description": "true",
    "limit": 30,
}
# Fixed and hourly have different minimums, so each type is its own query.
QUERIES = [
    {"project_types[]": ["fixed"], "min_price": 400},
    {"project_types[]": ["hourly"], "min_hourly_rate": 10},
]
# Dropped even if they slip past countries[]. The public API hides the client's own
# country (owner fields come back null), so currency is the only client-side signal.
EXCLUDED_CURRENCIES = {"INR"}

# Characters XML 1.0 forbids; one stray one in a description breaks the whole feed.
_XML_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class FreelancerSource:
    """Freelancer.com public project search API, filtered like SAVED_SEARCH_URL.
    https://developers.freelancer.com/docs/projects/projects#projects_projectsGetActive

    Also writes the results to data/freelancer.xml as an RSS feed.

    Read-only project search works without auth. If Freelancer starts requiring a
    token, set FREELANCER_OAUTH_TOKEN and it'll be sent automatically.
    """

    def __init__(self, oauth_token: str = ""):
        self.oauth_token = oauth_token

    def fetch(self) -> list[Job]:
        headers = {}
        if self.oauth_token:
            headers["freelancer-oauth-v1"] = self.oauth_token

        jobs: dict[str, tuple[int, Job]] = {}
        for extra in QUERIES:
            try:
                resp = requests.get(SEARCH_URL, params={**BASE_PARAMS, **extra}, headers=headers, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                log.warning("Freelancer.com search %s failed: %s", extra, e)
                continue

            for p in data.get("result", {}).get("projects", []):
                try:
                    if (p.get("currency") or {}).get("code") in EXCLUDED_CURRENCIES:
                        continue
                    job_id = f"freelancer:{p['id']}"
                    seo_url = p.get("seo_url", "")
                    url = f"https://www.freelancer.com/projects/{seo_url}" if seo_url else "https://www.freelancer.com/"
                    budget = p.get("budget") or {}
                    budget_str = ""
                    if budget:
                        lo, hi = budget.get("minimum"), budget.get("maximum")
                        currency = (p.get("currency") or {}).get("code", "")
                        per = "/hr" if p.get("type") == "hourly" else ""
                        if lo and hi:
                            budget_str = f"{lo:g}-{hi:g} {currency}{per}"
                        elif lo:
                            budget_str = f"{lo:g}+ {currency}{per}"

                    jobs[job_id] = (
                        p.get("time_submitted") or 0,
                        Job(
                            id=job_id,
                            platform="Freelancer.com",
                            title=p.get("title", "Untitled"),
                            url=url,
                            description=p.get("description") or p.get("preview_description", ""),
                            budget=budget_str,
                            prefiltered=True,
                        ),
                    )
                except Exception as e:
                    log.warning("Skipping malformed Freelancer.com project: %s", e)

        newest_first = sorted(jobs.values(), key=lambda t: t[0], reverse=True)
        if newest_first:  # both queries failing shouldn't wipe the published feed
            _write_rss(newest_first)
        return [job for _, job in newest_first]


def _x(s: str) -> str:
    return escape(_XML_BAD.sub("", s))


def _write_rss(jobs: list[tuple[int, Job]]) -> None:
    items = "\n".join(
        f"<item><title>{_x(j.title)}</title><link>{_x(j.url)}</link>"
        f'<guid isPermaLink="false">{j.id}</guid><pubDate>{formatdate(ts, usegmt=True)}</pubDate>'
        f"<description>{_x((j.budget + ' | ' if j.budget else '') + j.description)}</description></item>"
        for ts, j in jobs
    )
    FEED_FILE.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>\n'
        "<title>Freelancer.com saved search</title>\n"
        f"<link>{_x(SAVED_SEARCH_URL)}</link>\n"
        "<description>New Freelancer.com projects matching the saved search</description>\n"
        f"{items}\n</channel></rss>\n",
        encoding="utf-8",
    )
