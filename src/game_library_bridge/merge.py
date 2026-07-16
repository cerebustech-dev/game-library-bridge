"""Merge per-source fetch results into the versioned games.json document."""

from __future__ import annotations

import logging

from . import SCHEMA_VERSION
from .models import (
    SOURCE_ITAD_COLLECTION,
    SOURCE_ITAD_WAITLIST,
    SOURCE_STEAM,
    STATUS_OK,
    FetchResult,
    epoch_to_iso,
    normalize_title,
    utc_now_iso,
)

log = logging.getLogger("glb.merge")


def _new_entry(title: str) -> dict:
    return {
        "title": title,
        "normalized_title": normalize_title(title),
        "steam_appid": None,
        "itad_id": None,
        "itad_slug": None,
        "playtime_minutes": None,
        "added_at": None,
        "sources": [],
    }


def build_owned(steam: FetchResult, itad_collection: FetchResult, warnings: list[str]) -> list[dict]:
    """Union of Steam library and ITAD collection, matched by normalized title.

    ITAD's internal ids don't expose Steam appids, so cross-source identity is
    a title heuristic; unmatched entries are simply kept from both sides.
    Steam playtime wins; ITAD playtime (also minutes, synced from Steam) fills
    gaps for ITAD-only entries.
    """
    entries: list[dict] = []
    by_norm: dict[str, dict] = {}

    if steam.status == STATUS_OK:
        for raw in sorted(steam.games, key=lambda g: g["appid"]):
            entry = _new_entry(raw["name"])
            entry["steam_appid"] = raw["appid"]
            entry["playtime_minutes"] = int(raw.get("playtime_forever") or 0)
            entry["sources"] = [SOURCE_STEAM]
            entries.append(entry)
            if entry["normalized_title"] in by_norm:
                warnings.append(
                    f"merge: duplicate normalized title '{entry['normalized_title']}' in steam "
                    f"library (appids {by_norm[entry['normalized_title']]['steam_appid']} and {raw['appid']})"
                )
            else:
                by_norm[entry["normalized_title"]] = entry

    if itad_collection.status == STATUS_OK:
        for raw in sorted(itad_collection.games, key=lambda g: g["title"].lower()):
            norm = normalize_title(raw["title"])
            entry = by_norm.get(norm)
            if entry is None:
                entry = _new_entry(raw["title"])
                entry["sources"] = [SOURCE_ITAD_COLLECTION]
                entries.append(entry)
                by_norm[norm] = entry
            elif SOURCE_ITAD_COLLECTION not in entry["sources"]:
                entry["sources"].append(SOURCE_ITAD_COLLECTION)
            entry["itad_id"] = raw["id"]
            entry["itad_slug"] = raw.get("slug")
            entry["added_at"] = entry["added_at"] or epoch_to_iso(raw.get("added"))
            if entry["playtime_minutes"] is None and isinstance(raw.get("playtime"), int):
                entry["playtime_minutes"] = raw["playtime"]

    entries.sort(key=lambda e: (e["normalized_title"], e["title"]))
    return entries


def build_waitlisted(waitlist: FetchResult) -> list[dict]:
    entries = []
    if waitlist.status == STATUS_OK:
        for raw in sorted(waitlist.games, key=lambda g: g["title"].lower()):
            entry = _new_entry(raw["title"])
            entry["itad_id"] = raw["id"]
            entry["itad_slug"] = raw.get("slug")
            entry["added_at"] = epoch_to_iso(raw.get("added"))
            entry["sources"] = [SOURCE_ITAD_WAITLIST]
            del entry["playtime_minutes"]  # not meaningful for unowned games
            del entry["steam_appid"]
            entries.append(entry)
    entries.sort(key=lambda e: (e["normalized_title"], e["title"]))
    return entries


def build_snapshot(
    steam: FetchResult,
    itad_collection: FetchResult,
    itad_waitlist: FetchResult,
    steam_id: str,
    itad_user: str,
    previous: dict | None,
    generated_at: str | None = None,
) -> dict:
    warnings: list[str] = []
    for result in (steam, itad_collection, itad_waitlist):
        warnings.extend(result.warnings)
        if result.status != STATUS_OK:
            warnings.append(f"{result.source}: not fetched ({result.status}): {result.error}")

    owned = build_owned(steam, itad_collection, warnings)
    waitlisted = build_waitlisted(itad_waitlist)

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_version": (previous or {}).get("snapshot_version", 0) + 1,
        "generated_at": generated_at or utc_now_iso(),
        "identity": {"steam_id": steam_id, "itad_user": itad_user},
        "sources": {
            SOURCE_STEAM: steam.provenance(),
            SOURCE_ITAD_COLLECTION: itad_collection.provenance(),
            SOURCE_ITAD_WAITLIST: itad_waitlist.provenance(),
        },
        "owned": owned,
        "waitlisted": waitlisted,
        "warnings": warnings,
    }
    log.info(
        "snapshot built",
        extra={
            "snapshot_version": snapshot["snapshot_version"],
            "owned": len(owned),
            "waitlisted": len(waitlisted),
            "warnings": len(warnings),
        },
    )
    return snapshot
