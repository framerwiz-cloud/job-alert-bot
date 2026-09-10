from dataclasses import dataclass


@dataclass
class Job:
    id: str
    platform: str
    title: str
    url: str
    description: str
    budget: str = ""
    # True when the source already filtered server-side (e.g. Freelancer saved search).
    prefiltered: bool = False

    def matches_keywords(self, keywords: list[str]) -> bool:
        if self.prefiltered or not keywords:
            return True
        haystack = f"{self.title} {self.description}".lower()
        return any(k in haystack for k in keywords)
