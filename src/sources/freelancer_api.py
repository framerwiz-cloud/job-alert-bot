import logging

import requests

from .base import Job

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.freelancer.com/api/projects/0.1/projects/active"


class FreelancerSource:
    """Freelancer.com public project search API.
    https://developers.freelancer.com/docs/projects/projects#projects_projectsGetActive

    Read-only project search works without auth. If Freelancer starts requiring a
    token, set FREELANCER_OAUTH_TOKEN and it'll be sent automatically.
    """

    def __init__(self, keywords: list[str], oauth_token: str = ""):
        self.keywords = keywords
        self.oauth_token = oauth_token

    def fetch(self) -> list[Job]:
        if not self.keywords:
            return []

        headers = {}
        if self.oauth_token:
            headers["freelancer-oauth-v1"] = self.oauth_token

        jobs: dict[str, Job] = {}
        for kw in self.keywords:
            try:
                resp = requests.get(
                    SEARCH_URL,
                    params={
                        "query": kw,
                        "compact": "true",
                        "full_description": "true",
                        "job_details": "true",
                        "limit": 20,
                    },
                    headers=headers,
                    timeout=20,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                log.warning("Freelancer.com search for %r failed: %s", kw, e)
                continue

            for p in data.get("result", {}).get("projects", []):
                try:
                    job_id = f"freelancer:{p['id']}"
                    seo_url = p.get("seo_url", "")
                    url = f"https://www.freelancer.com/projects/{seo_url}" if seo_url else "https://www.freelancer.com/"
                    budget = p.get("budget") or {}
                    budget_str = ""
                    if budget:
                        lo, hi = budget.get("minimum"), budget.get("maximum")
                        currency = (p.get("currency") or {}).get("code", "")
                        if lo and hi:
                            budget_str = f"{lo}-{hi} {currency}".strip()
                        elif lo:
                            budget_str = f"{lo}+ {currency}".strip()

                    jobs[job_id] = Job(
                        id=job_id,
                        platform="Freelancer.com",
                        title=p.get("title", "Untitled"),
                        url=url,
                        description=p.get("preview_description", ""),
                        budget=budget_str,
                    )
                except Exception as e:
                    log.warning("Skipping malformed Freelancer.com project: %s", e)

        return list(jobs.values())
