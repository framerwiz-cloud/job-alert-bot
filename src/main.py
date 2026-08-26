from __future__ import annotations

import argparse
import logging
import time

from .config import env, load_config
from .dedup import SeenStore
from .notify_slack import send_alert
from .proposal import draft_proposal
from .sources.email_source import UpworkEmailSource
from .sources.freelancer_api import FreelancerSource
from .sources.rss_source import RssSource

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("job-alert-bot")


def budget_ok(job, min_budget: float) -> bool:
    if min_budget <= 0 or not job.budget:
        return True
    digits = "".join(c for c in job.budget if c.isdigit() or c == ".")
    try:
        return float(digits.split(".")[0] or 0) >= min_budget
    except ValueError:
        return True


def main():
    ap = argparse.ArgumentParser(description="Find new freelance jobs and draft proposals.")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be alerted instead of posting to Slack. Does not record jobs as seen.",
    )
    ap.add_argument("--no-ai", action="store_true", help="Skip proposal drafting (useful when testing sources).")
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after this many alerts. Useful on the very first run so you don't get a flood.",
    )
    ap.add_argument(
        "--catch-up",
        action="store_true",
        help="Mark every job found right now as already seen, without sending anything. "
        "Run this once before scheduling so you start from a clean slate instead of "
        "getting alerted about your whole backlog.",
    )
    args = ap.parse_args()

    cfg = load_config()
    keywords = cfg["keywords"]
    min_budget = cfg.get("min_budget", 0)
    profile = cfg.get("profile", {})
    models = cfg.get("openrouter_models") or []

    slack_webhook = env("SLACK_WEBHOOK_URL")
    openrouter_key = "" if args.no_ai else env("OPENROUTER_API_KEY")

    sources = [
        UpworkEmailSource(
            host=env("IMAP_HOST", "imap.gmail.com"),
            user=env("IMAP_USER"),
            # Google displays app passwords in "abcd efgh ijkl mnop" form; the spaces aren't part of it.
            password=env("IMAP_PASSWORD").replace(" ", ""),
            folder=env("IMAP_FOLDER", "INBOX"),
            lookback_days=int(env("IMAP_LOOKBACK_DAYS", "2") or 2),
        ),
        FreelancerSource(keywords, env("FREELANCER_OAUTH_TOKEN")),
        RssSource("Guru", env("GURU_RSS_URL")),
        RssSource("PeoplePerHour", env("PPH_RSS_URL")),
    ]

    seen = SeenStore()
    new_count = 0

    for source in sources:
        if args.limit and new_count >= args.limit:
            break
        try:
            jobs = source.fetch()
        except Exception as e:
            log.error("Source %s failed entirely: %s", getattr(source, "platform", source), e)
            continue

        for job in jobs:
            if args.limit and new_count >= args.limit:
                break
            if not seen.is_new(job.id):
                continue
            if not job.matches_keywords(keywords):
                if not args.dry_run:
                    seen.mark_seen(job.id)
                continue
            if not budget_ok(job, min_budget):
                if not args.dry_run:
                    seen.mark_seen(job.id)
                continue

            new_count += 1

            if args.catch_up:
                seen.mark_seen(job.id)
                continue

            if args.dry_run:
                print("\n" + "=" * 70)
                print(f"[{job.platform}] {job.title}")
                print(f"  url:    {job.url}")
                print(f"  budget: {job.budget or '(none listed)'}")
                print(f"  desc:   {job.description[:300]}")
                continue

            log.info("New match: [%s] %s", job.platform, job.title)
            proposal = draft_proposal(job, profile, models, openrouter_key)
            send_alert(slack_webhook, job, proposal)
            seen.mark_seen(job.id)
            time.sleep(1)  # be polite to OpenRouter's free-tier rate limit

    if args.dry_run:
        print("\n" + "=" * 70)
        print(f"DRY RUN: {new_count} job(s) would have been sent to Slack. Nothing was posted or marked seen.")
    elif args.catch_up:
        seen.save()
        log.info("Caught up: %d existing job(s) marked as seen. Nothing was sent.", new_count)
        log.info("From now on you'll only be alerted about jobs newer than this point.")
    else:
        seen.save()
        log.info("Done. %d new job(s) alerted.", new_count)


if __name__ == "__main__":
    main()
