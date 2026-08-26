# Job Alert Bot

Watches Upwork, Freelancer.com, Guru, and PeoplePerHour for new jobs matching your
niche (Framer / Webflow / WordPress Elementor / web design), drafts a proposal for
each one with a free OpenRouter model, and posts it to Slack for you to review and
send yourself. It never auto-submits bids.

## What actually works out of the box, and what needs a workaround

| Platform | Method | Cost |
|---|---|---|
| Upwork | Job-alert **emails** read over IMAP | Free, no approval |
| Freelancer.com | Public project search API | Free, official |
| Guru | No public API or RSS | Needs a free feed-generator workaround (below) |
| PeoplePerHour | No public API or RSS | Needs a free feed-generator workaround (below) |

**On Upwork:** Upwork [shut down RSS feeds in August 2024](https://support.upwork.com/hc/en-us/articles/52052528243731-RSS-deprecation).
There is no feed to subscribe to any more, and no RSS icon on saved searches. The
free replacement used here is Upwork's own **email alerts**: you turn on instant
alerts for a saved search, and the bot reads those emails out of a Gmail mailbox
over IMAP. Expect a 15–60 minute delay, which is Upwork's alert cadence, not the
bot's.

For real-time Upwork data, request an [official API key](https://support.upwork.com/hc/en-us/articles/115015857647-How-to-request-an-API-key-from-Upwork).
It's free, available on any membership plan for personal/internal use, and takes
about a week to approve. The email route works fine in the meantime.

Guru and PPH don't expose a free official feed either. Rather than scrape their
pages (fragile and against most sites' terms), this bot treats them as optional
RSS sources — you point a free tool like [rss.app](https://rss.app) (free tier)
at your saved-search results page, and paste the generated RSS URL into `.env`.
If you skip this, the bot still runs fine on Upwork + Freelancer.com.

## 1. Install

```bash
cd ~/job-alert-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 2. Get your free credentials

Open `.env` and fill these in (every step below is free):

- **Slack webhook** — [api.slack.com/apps](https://api.slack.com/apps) → *Create New App* → *From scratch* → *Incoming Webhooks* → *Activate* → *Add New Webhook to Workspace* → pick a channel → copy the URL into `SLACK_WEBHOOK_URL`.
- **OpenRouter key** — [openrouter.ai](https://openrouter.ai) → sign up → *Keys* → *Create Key* → paste into `OPENROUTER_API_KEY`. No model configuration needed — `config.yaml` lists several free models and the bot tries them in order, because free models rate-limit aggressively (HTTP 429) and get retired without notice. If every listed model fails, it queries OpenRouter for whatever is free right now and uses that. Seeing a few `429` warnings in the log is normal, not a failure.
- **Upwork email alerts** — on upwork.com create a saved search for your keywords and turn its email alerts **on** (set to *Instantly*). Then enable 2-Step Verification on the Gmail account receiving them, create an App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), and set `IMAP_USER` (the address) and `IMAP_PASSWORD` (the 16-char app password) in `.env`. A regular Gmail password will not work — Google blocks it for IMAP.
- **Freelancer.com** — nothing required. The public search API works unauthenticated. If it ever starts requiring auth, get a free token at developers.freelancer.com → *My Apps* → *Create App* and put it in `FREELANCER_OAUTH_TOKEN`.
- **Guru / PPH (optional)** — set up a saved search on each site, copy the results page URL, generate a free RSS feed for it via rss.app (or similar), paste into `GURU_RSS_URL` / `PPH_RSS_URL`.

## 3. Customize your profile

`config.yaml` already has your niche keywords set (Framer, Webflow, WordPress,
Elementor, Web Design, Landing Page). Edit the `profile:` section with your real
name, rate, and portfolio link — this is what OpenRouter uses to personalize each
proposal draft.

## 3.5 Check your setup

```bash
venv/bin/python check_setup.py
```

Tells you exactly which credentials are working and which are missing. It only
reads — it posts nothing to Slack and never prints your secrets.

## 4. Run it

Preview what it found without posting anything to Slack:

```bash
python -m src.main --dry-run --no-ai
```

That prints every job it would alert on and marks nothing as seen, so you can run
it as often as you like while tuning your keywords. When the output looks right:

```bash
python -m src.main --limit 3
```

`--limit` caps how many alerts a run sends. Use it on your first real run — otherwise
you'll get a message for every currently-open matching job at once. Drop the flag
once you're happy:

```bash
python -m src.main
```

### Option A — run locally on a schedule (macOS `launchd`/cron)

Add a cron entry to run every 15 minutes:

```bash
crontab -e
```

```
*/15 * * * * cd ~/job-alert-bot && venv/bin/python -m src.main >> data/run.log 2>&1
```

Your Mac needs to be on for this to fire.

### Option B — free cloud scheduling via GitHub Actions (runs even if your Mac is off)

1. Push this folder to a new GitHub repo (public or private, both get free Actions minutes on this cron-light schedule).
2. In the repo, go to **Settings → Secrets and variables → Actions** and add each value from your `.env` as a repo secret with the same name (`SLACK_WEBHOOK_URL`, `OPENROUTER_API_KEY`, `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD`, `FREELANCER_OAUTH_TOKEN`, `GURU_RSS_URL`, `PPH_RSS_URL`).
3. The included workflow at `.github/workflows/job_alerts.yml` runs every 15 minutes automatically and commits `data/seen.json` back to the repo after each run, so it won't double-alert you across runs.

## How it filters and drafts

- Each source is fetched, then every job is checked against the `keywords` list in
  `config.yaml` (title + description, case-insensitive). Upwork is already
  filtered by your saved search, so this is a secondary safety net there.
- New (never-seen) matching jobs get a proposal drafted by your configured
  OpenRouter model, using the `profile` block in `config.yaml` for tone/skills/rate.
- A Slack message is sent with the job title, link, budget, description snippet,
  and the draft proposal — you copy-paste and submit it yourself.
- Seen job IDs are stored in `data/seen.json` so nothing alerts twice.

## Safety notes

- This only reads publicly available job listings — it doesn't log into any
  platform or automate bidding.
- If Freelancer.com's public search endpoint ever changes shape, the bot logs a
  warning and skips that source rather than crashing the whole run.
- OpenRouter free-tier models can rate-limit or occasionally fail; if a draft
  can't be generated, the Slack alert still goes out without one so you never
  miss a job.
