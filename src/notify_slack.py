from __future__ import annotations

import logging

import requests

from .sources.base import Job

log = logging.getLogger(__name__)


def send_alert(webhook_url: str, job: Job, proposal: str | None) -> None:
    if not webhook_url:
        log.warning("SLACK_WEBHOOK_URL not set, skipping alert for %s", job.url)
        return

    header = f"*{job.platform}* — <{job.url}|{job.title}>"
    if job.budget:
        header += f"  ·  💰 {job.budget}"

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": job.description[:600] + ("…" if len(job.description) > 600 else "")},
        },
    ]

    if proposal:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Draft proposal (review before sending):*\n>{proposal}"},
            }
        )
    else:
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "_No AI draft available — write your own proposal._"}]}
        )

    payload = {
        "text": f"New job on {job.platform}: {job.title}",
        "blocks": blocks,
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        log.error("Failed to send Slack alert for %s: %s", job.url, e)
