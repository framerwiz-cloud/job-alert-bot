import logging

import feedparser

from .base import Job

log = logging.getLogger(__name__)


class RssSource:
    """Generic RSS-based source. Used for Upwork saved-search feeds and, optionally,
    Guru/PPH via a third-party feed generator pointed at a saved-search page."""

    def __init__(self, platform: str, feed_url: str):
        self.platform = platform
        self.feed_url = feed_url

    def fetch(self) -> list[Job]:
        if not self.feed_url:
            log.info("%s: no feed URL configured, skipping (this source is optional)", self.platform)
            return []
        parsed = feedparser.parse(self.feed_url)
        if parsed.bozo and not parsed.entries:
            log.warning("%s: could not parse RSS feed (%s)", self.platform, parsed.get("bozo_exception"))
            return []

        jobs = []
        for entry in parsed.entries:
            job_id = f"{self.platform}:{entry.get('id') or entry.get('link')}"
            jobs.append(
                Job(
                    id=job_id,
                    platform=self.platform,
                    title=entry.get("title", "Untitled"),
                    url=entry.get("link", ""),
                    description=entry.get("summary", ""),
                )
            )
        return jobs
