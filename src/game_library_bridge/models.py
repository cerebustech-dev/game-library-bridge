"""Shared datatypes and title normalization."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone

SOURCE_STEAM = "steam"
SOURCE_ITAD_COLLECTION = "itad_collection"
SOURCE_ITAD_WAITLIST = "itad_waitlist"
ALL_SOURCES = (SOURCE_STEAM, SOURCE_ITAD_COLLECTION, SOURCE_ITAD_WAITLIST)

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"


@dataclass
class FetchResult:
    """Outcome of fetching one source, successful or not."""

    source: str
    status: str = STATUS_OK
    games: list[dict] = field(default_factory=list)
    fetched_at: str | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    via: str | None = None  # e.g. "json-api", "playwright"

    def provenance(self) -> dict:
        return {
            "status": self.status,
            "fetched_at": self.fetched_at,
            "count": len(self.games) if self.status == STATUS_OK else None,
            "via": self.via,
            "error": self.error,
        }


_TRADEMARKS = re.compile(r"[™®©]")  # ™ ® ©
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """Canonical form used to match the same game across sources.

    Lowercase, ASCII-fold, strip trademark symbols and punctuation, collapse
    whitespace. "Mass Effect™ Legendary Edition" == "mass effect legendary edition".
    """
    text = _TRADEMARKS.sub("", title)  # before NFKD, which would fold ™ into "tm"
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.replace("&", " and ")
    text = _PUNCT.sub(" ", text.lower())
    return _WS.sub(" ", text).strip()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch_to_iso(epoch: int | float | None) -> str | None:
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (OverflowError, OSError, ValueError):
        return None
