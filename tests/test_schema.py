import copy

import pytest

from game_library_bridge.schema import SnapshotValidationError, load_schema, validate_snapshot


def test_built_snapshot_validates(snapshot):
    validate_snapshot(snapshot)  # must not raise


def test_schema_is_strict_about_extra_keys(snapshot):
    broken = copy.deepcopy(snapshot)
    broken["surprise"] = True
    with pytest.raises(SnapshotValidationError):
        validate_snapshot(broken)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.pop("owned"),
        lambda s: s.__setitem__("snapshot_version", 0),
        lambda s: s.__setitem__("generated_at", "yesterday"),
        lambda s: s["owned"][0].__setitem__("sources", []),
        lambda s: s["owned"][0].__setitem__("playtime_minutes", -5),
        lambda s: s["owned"][0].__setitem__("sources", ["itad_waitlist"]),
        lambda s: s["sources"]["steam"].__setitem__("status", "maybe"),
        lambda s: s["identity"].__setitem__("steam_id", "not-a-steamid"),
        lambda s: s["waitlisted"][0].__setitem__("title", ""),
    ],
    ids=[
        "missing-owned",
        "zero-snapshot-version",
        "bad-timestamp",
        "empty-sources-list",
        "negative-playtime",
        "wrong-source-enum",
        "bad-status-enum",
        "bad-steam-id",
        "empty-title",
    ],
)
def test_invalid_snapshots_rejected(snapshot, mutate):
    broken = copy.deepcopy(snapshot)
    mutate(broken)
    with pytest.raises(SnapshotValidationError):
        validate_snapshot(broken)


def test_schema_itself_is_valid_draft_2020_12():
    import jsonschema

    jsonschema.Draft202012Validator.check_schema(load_schema())
