from dataclasses import dataclass


@dataclass
class Job:
    id: str
    platform: str
    title: str
    url: str
    description: str
    budget: str = ""

    def matches_keywords(self, keywords: list[str]) -> bool:
        if not keywords:
            return True
        haystack = f"{self.title} {self.description}".lower()
        return any(k in haystack for k in keywords)
