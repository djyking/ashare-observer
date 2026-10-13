from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class SourceResult:
    source_id: str
    source_name: str
    source_type: str
    url: str
    status: str = "success"
    fetched_at: str = field(default_factory=utcnow)
    items: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    coverage: str = ""
    metrics: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)
