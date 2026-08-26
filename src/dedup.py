import json

from .config import DATA_DIR, SEEN_FILE

MAX_SEEN = 2000


class SeenStore:
    """Tracks job IDs we've already alerted on, so re-runs don't double-post.

    Keeps only the most recent MAX_SEEN ids so the file doesn't grow forever.
    """

    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)
        if SEEN_FILE.exists():
            self.ids: list[str] = json.loads(SEEN_FILE.read_text())
        else:
            self.ids = []
        self._id_set = set(self.ids)

    def is_new(self, job_id: str) -> bool:
        return job_id not in self._id_set

    def mark_seen(self, job_id: str) -> None:
        if job_id in self._id_set:
            return
        self.ids.append(job_id)
        self._id_set.add(job_id)
        if len(self.ids) > MAX_SEEN:
            dropped = self.ids[:-MAX_SEEN]
            self.ids = self.ids[-MAX_SEEN:]
            for d in dropped:
                self._id_set.discard(d)

    def save(self) -> None:
        SEEN_FILE.write_text(json.dumps(self.ids, indent=2))
