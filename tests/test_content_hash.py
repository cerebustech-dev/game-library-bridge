import copy

from game_library_bridge.merge import build_snapshot
from game_library_bridge.snapshot import compute_content_hash


def rebuild(ok_results, previous=None, generated_at="2026-07-17T09:00:00Z"):
    steam, coll, wait = ok_results
    return build_snapshot(
        steam, coll, wait,
        steam_id="76561197970928054",
        itad_user="arcca",
        previous=previous,
        generated_at=generated_at,
    )


def test_counts_match_lists(snapshot):
    assert snapshot["owned_count"] == len(snapshot["owned"]) == 4
    assert snapshot["waitlisted_count"] == len(snapshot["waitlisted"]) == 2


def test_hash_format(snapshot):
    assert snapshot["content_hash"].startswith("sha256:")
    assert len(snapshot["content_hash"]) == len("sha256:") + 64


def test_hash_stable_across_runs_with_same_data(snapshot, ok_results):
    later = rebuild(ok_results, previous=snapshot)  # new version + timestamp

    assert later["snapshot_version"] != snapshot["snapshot_version"]
    assert later["generated_at"] != snapshot["generated_at"]
    assert later["content_hash"] == snapshot["content_hash"]


def test_hash_ignores_fetch_metadata_and_warnings(snapshot):
    noisy = copy.deepcopy(snapshot)
    for src in noisy["sources"].values():
        src["fetched_at"] = "2027-01-01T00:00:00Z"
        src["via"] = "playwright"
    noisy["warnings"] = ["something incidental"]

    assert compute_content_hash(noisy) == snapshot["content_hash"]


def test_hash_changes_when_library_changes(snapshot):
    changed = copy.deepcopy(snapshot)
    changed["owned"][0]["playtime_minutes"] = 999999

    assert compute_content_hash(changed) != snapshot["content_hash"]

    removed = copy.deepcopy(snapshot)
    removed["waitlisted"].pop()

    assert compute_content_hash(removed) != snapshot["content_hash"]


def test_legacy_snapshot_without_new_fields_still_validates(snapshot):
    """A 1.0.0 snapshot must stay guard-eligible after the 1.1.0 upgrade."""
    from game_library_bridge.schema import validate_snapshot

    legacy = copy.deepcopy(snapshot)
    legacy["schema_version"] = "1.0.0"
    del legacy["content_hash"]
    del legacy["owned_count"]
    del legacy["waitlisted_count"]

    validate_snapshot(legacy)  # must not raise
