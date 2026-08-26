import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    cfg["keywords"] = [k.lower() for k in cfg.get("keywords", [])]
    return cfg


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


DATA_DIR = ROOT / "data"
SEEN_FILE = DATA_DIR / "seen.json"
