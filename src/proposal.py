from __future__ import annotations

import logging
import re

import requests

from .sources.base import Job

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"

# Reasoning models sometimes emit their scratchpad inline. Strip it.
THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.S | re.I)
PREAMBLE_RE = re.compile(
    r"^\s*(we need to|the user (is |wants|asks)|okay,? |alright,? |let me |i should |first,? i)"
    r"[^\n]*\n+",
    re.I,
)


def _clean(text: str) -> str:
    text = THINK_RE.sub("", text)
    # Drop a leading reasoning sentence if the model leaked one.
    for _ in range(3):
        new = PREAMBLE_RE.sub("", text)
        if new == text:
            break
        text = new
    # Models often wrap the proposal in quotes or a markdown fence.
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip().strip('"').strip()


def discover_free_models(limit: int = 8) -> list[str]:
    """Ask OpenRouter which models are free right now. Used as a last-resort
    fallback when every configured model is rate-limited or retired."""
    try:
        resp = requests.get(MODELS_URL, timeout=20)
        resp.raise_for_status()
        free = [m["id"] for m in resp.json().get("data", []) if m.get("id", "").endswith(":free")]
        return free[:limit]
    except Exception as e:
        log.warning("Could not fetch OpenRouter model list: %s", e)
        return []


def _try_model(model: str, system: str, user: str, api_key: str) -> str | None:
    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": 700,
            },
            # Short on purpose: a slow free model should be skipped in favor of the
            # next one in the fallback list, not held onto for a minute-plus.
            timeout=20,
        )
    except Exception as e:
        log.warning("  %s -> request failed: %s", model, e)
        return None

    if resp.status_code != 200:
        # 429 = rate limited, 404 = model retired. Both mean "try the next one".
        log.warning("  %s -> HTTP %s", model, resp.status_code)
        return None

    try:
        text = _clean(resp.json()["choices"][0]["message"]["content"])
        return text or None
    except Exception as e:
        log.warning("  %s -> unexpected response shape: %s", model, e)
        return None


def draft_proposal(job: Job, profile: dict, models: list[str], api_key: str) -> str | None:
    """Draft a proposal, walking down the model list until one succeeds.

    Free OpenRouter models rate-limit aggressively and get retired without notice,
    so a single hardcoded model is not reliable enough to depend on.
    """
    if not api_key:
        return None

    max_words = profile.get("proposal_length_words", 120)
    system = (
        f"You write short, specific freelance proposal drafts for {profile.get('name', 'a freelancer')}, "
        f"whose skills are: {profile.get('skills', '')}. Rate/availability: {profile.get('rate', '')}. "
        f"Tone: {profile.get('tone', 'confident and concise')}. "
        f"Keep it under {max_words} words. No greetings like 'Dear Sir/Madam'. "
        "Reference specifics from the job post so it doesn't read as generic. "
        "End with one direct question or next step. "
        "Output ONLY the proposal text itself -- no preamble, no reasoning, no markdown fences, no quotes."
    )
    user = f"Job title: {job.title}\nPlatform: {job.platform}\nJob description:\n{job.description[:3000]}"

    for model in models:
        text = _try_model(model, system, user, api_key)
        if text:
            return text

    log.info("All configured models failed; asking OpenRouter what's free right now...")
    for model in discover_free_models():
        if model in models:
            continue
        text = _try_model(model, system, user, api_key)
        if text:
            log.info("Fell back to %s -- consider adding it to config.yaml", model)
            return text

    log.warning("No model could draft a proposal for %s", job.url)
    return None
