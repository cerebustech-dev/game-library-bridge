"""Snapshot schema loading and validation."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

import jsonschema


class SnapshotValidationError(ValueError):
    pass


@lru_cache(maxsize=1)
def load_schema() -> dict:
    ref = resources.files("game_library_bridge") / "schemas" / "games.schema.json"
    return json.loads(ref.read_text(encoding="utf-8"))


def validate_snapshot(snapshot: dict) -> None:
    """Raise SnapshotValidationError with all violations if invalid."""
    validator = jsonschema.Draft202012Validator(load_schema())
    errors = sorted(validator.iter_errors(snapshot), key=lambda e: list(e.absolute_path))
    if errors:
        details = "; ".join(
            f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
            for err in errors[:10]
        )
        more = f" (+{len(errors) - 10} more)" if len(errors) > 10 else ""
        raise SnapshotValidationError(f"snapshot failed schema validation: {details}{more}")
