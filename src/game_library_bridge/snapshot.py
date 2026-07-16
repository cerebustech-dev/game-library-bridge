"""Snapshot persistence and the overwrite guard.

The guard's contract: a valid previous snapshot is never overwritten with
empty or suspiciously incomplete data. A rejected candidate is written to
<output>.rejected.json for inspection and the run exits nonzero.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import tempfile
from pathlib import Path

from .models import STATUS_OK
from .schema import SnapshotValidationError, validate_snapshot

log = logging.getLogger("glb.snapshot")

# Fields whose hash-relevant content is the library itself. Run metadata
# (timestamps, snapshot_version, provenance, warnings) is deliberately
# excluded so the hash changes iff the actual game data changes.
_HASHED_FIELDS = ("identity", "owned", "waitlisted")


def compute_content_hash(snapshot: dict) -> str:
    """Stable sha256 over the library content (identity + owned + waitlisted).

    Canonical serialization: sorted keys, compact separators, UTF-8. Two
    snapshots of the same library produce the same hash regardless of when or
    how they were fetched.
    """
    doc = {key: snapshot.get(key) for key in _HASHED_FIELDS}
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_previous(path: Path) -> tuple[dict | None, list[str]]:
    """Load and validate the previous snapshot.

    Returns (snapshot or None, warnings). A corrupt/invalid previous file is
    treated as absent — but reported — so a bad state can't wedge the pipeline
    forever, while the guard still protects any *valid* previous snapshot.
    """
    if not path.exists():
        return None, []
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
        validate_snapshot(previous)
        return previous, []
    except (json.JSONDecodeError, SnapshotValidationError) as exc:
        warning = f"previous snapshot at {path} is invalid and was ignored: {exc}"
        log.warning(warning)
        return None, [warning]


def evaluate_guard(
    previous: dict | None,
    candidate: dict,
    min_ratio: float = 0.5,
    small_list: int = 10,
    allow_degraded: bool = False,
) -> list[str]:
    """Return the list of reasons the candidate must NOT replace the previous
    snapshot. Empty list means it is safe to write."""
    if previous is None:
        return []

    reasons: list[str] = []

    statuses = [s["status"] for s in candidate["sources"].values()]
    if STATUS_OK not in statuses:
        reasons.append("no source fetched successfully")

    for key in ("owned", "waitlisted"):
        prev_n = len(previous.get(key, []))
        new_n = len(candidate.get(key, []))
        if prev_n > 0 and new_n == 0:
            reasons.append(f"{key} became empty (previous snapshot had {prev_n})")
        elif prev_n > small_list and new_n < math.ceil(prev_n * min_ratio):
            reasons.append(
                f"{key} shrank suspiciously: {prev_n} -> {new_n} "
                f"(below {min_ratio:.0%} guard threshold)"
            )

    if not allow_degraded:
        for name, src in candidate["sources"].items():
            prev_src = previous.get("sources", {}).get(name, {})
            previously_contributed = (
                prev_src.get("status") == STATUS_OK and (prev_src.get("count") or 0) > 0
            )
            if src["status"] != STATUS_OK and previously_contributed:
                reasons.append(
                    f"source '{name}' is {src['status']} but previously contributed "
                    f"{prev_src.get('count')} games (use --allow-degraded to accept)"
                )

    return reasons


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_snapshot(path: Path, snapshot: dict) -> None:
    validate_snapshot(snapshot)  # a snapshot that fails its own schema is a bug
    _atomic_write_json(path, snapshot)
    log.info(
        "snapshot written",
        extra={
            "path": str(path),
            "snapshot_version": snapshot["snapshot_version"],
            "owned": len(snapshot["owned"]),
            "waitlisted": len(snapshot["waitlisted"]),
        },
    )


def rejected_path(output_path: Path) -> Path:
    return output_path.with_name(output_path.stem + ".rejected.json")


def write_rejected(output_path: Path, candidate: dict, reasons: list[str]) -> Path:
    target = rejected_path(output_path)
    _atomic_write_json(target, {"rejected_because": reasons, "candidate": candidate})
    log.error(
        "snapshot REJECTED by guard; previous snapshot kept",
        extra={"reasons": reasons, "rejected_candidate": str(target)},
    )
    return target
