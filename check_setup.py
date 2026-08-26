"""Verifies your .env is wired up correctly. Safe to run as often as you like --
it reads only, sends nothing to Slack, and never prints your secrets."""

import imaplib
import sys
from datetime import datetime, timedelta

from src.config import env, load_config

OK, BAD, WARN = "\033[92m✅\033[0m", "\033[91m❌\033[0m", "\033[93m⚠️ \033[0m"


def mask(value: str) -> str:
    if not value:
        return "(empty)"
    return f"{value[:6]}…{value[-4:]} ({len(value)} chars)"


def main():
    problems = []
    print("\n=== Checking your setup ===\n")

    # --- config.yaml ---
    try:
        cfg = load_config()
        print(f"{OK} config.yaml: {len(cfg['keywords'])} keywords -> {', '.join(cfg['keywords'])}")
    except Exception as e:
        print(f"{BAD} config.yaml could not be read: {e}")
        problems.append("Fix config.yaml")

    # --- Slack ---
    hook = env("SLACK_WEBHOOK_URL")
    if not hook:
        print(f"{BAD} SLACK_WEBHOOK_URL is empty")
        problems.append("Add SLACK_WEBHOOK_URL to .env")
    elif not hook.startswith("https://hooks.slack.com/"):
        print(f"{BAD} SLACK_WEBHOOK_URL doesn't look like a Slack webhook: {mask(hook)}")
        problems.append("Check your Slack webhook URL")
    else:
        print(f"{OK} SLACK_WEBHOOK_URL looks valid: {mask(hook)}")

    # --- IMAP / Upwork emails ---
    host, user, pw = env("IMAP_HOST"), env("IMAP_USER"), env("IMAP_PASSWORD").replace(" ", "")
    folder = env("IMAP_FOLDER", "INBOX")

    if not user or not pw:
        print(f"{WARN} IMAP not configured yet -- Upwork emails will be skipped.")
        print("     (Freelancer.com still works without this.)")
        problems.append("Add IMAP_USER and IMAP_PASSWORD to .env for Upwork")
    else:
        if len(pw) != 16:
            print(f"{WARN} IMAP_PASSWORD is {len(pw)} chars. Google app passwords are 16.")
            print("     If login fails below, you may have used your normal Gmail password.")
        try:
            conn = imaplib.IMAP4_SSL(host)
            conn.login(user, pw)
            print(f"{OK} IMAP login succeeded for {user}")

            status, _ = conn.select(folder, readonly=True)
            if status != "OK":
                print(f"{BAD} Could not open folder {folder!r}")
                problems.append(f"Check IMAP_FOLDER (currently {folder!r})")
            else:
                since = (datetime.now() - timedelta(days=14)).strftime("%d-%b-%Y")
                _, data = conn.search(None, f'(FROM "upwork.com" SINCE {since})')
                count = len(data[0].split()) if data and data[0] else 0
                if count:
                    print(f"{OK} Found {count} email(s) from Upwork in {folder} (last 14 days)")
                else:
                    print(f"{WARN} No Upwork emails found in {folder} in the last 14 days.")
                    print("     Either alerts aren't on yet, or a Gmail filter is archiving them.")
                    print('     If they\'re being archived, set IMAP_FOLDER="[Gmail]/All Mail" in .env')
                    problems.append("Turn on Upwork saved-search email alerts")
            conn.logout()
        except imaplib.IMAP4.error as e:
            print(f"{BAD} IMAP login failed: {e}")
            print("     Most common cause: using your normal Gmail password instead of a")
            print("     16-character App Password from myaccount.google.com/apppasswords")
            problems.append("Fix IMAP_USER / IMAP_PASSWORD")
        except Exception as e:
            print(f"{BAD} Could not connect to {host}: {e}")
            problems.append("Check IMAP_HOST")

    # --- Summary ---
    print("\n=== Summary ===\n")
    if problems:
        print("Still to do:")
        for p in problems:
            print(f"  • {p}")
        print("\nRun this again after fixing them.")
    else:
        print("Everything checks out. Preview what it found with:")
        print("  venv/bin/python -m src.main --dry-run")
    print()
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
