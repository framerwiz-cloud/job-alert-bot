from __future__ import annotations

import logging

import requests

from .sources.base import Job

log = logging.getLogger(__name__)

PLATFORM_EMOJI = {
    "Upwork": "🟢",
    "Freelancer.com": "🔵",
    "Guru": "🟣",
    "PeoplePerHour": "🟠",
}


def send_alert(webhook_url: str, job: Job) -> None:
    if not webhook_url:
        log.warning("SLACK_WEBHOOK_URL not set, skipping alert for %s", job.url)
        return

    emoji = PLATFORM_EMOJI.get(job.platform, "⚪")

    context_bits = [f"{emoji} *{job.platform}*"]
    if job.budget:
        context_bits.append(f"💰 {job.budget}")

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*<{job.url}|{job.title}>*"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "  ·  ".join(context_bits)}],
        },
    ]

    description = job.description.strip()
    if description:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": description[:700] + ("…" if len(description) > 700 else ""),
                },
            }
        )

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View job"},
                    "url": job.url,
                    "style": "primary",
                }
            ],
        }
    )

    payload = {
        # Fallback text drives the mobile/desktop notification preview.
        "text": f"{job.platform}: {job.title}",
        "blocks": blocks,
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        log.error("Failed to send Slack alert for %s: %s", job.url, e)
