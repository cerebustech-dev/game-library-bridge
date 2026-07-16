import copy
import json

import pytest

from game_library_bridge.schema import SnapshotValidationError
from game_library_bridge.snapshot import (
    evaluate_guard,
    load_previous,
    rejected_path,
    write_rejected,
    write_snapshot,
)


@pytest.fixture
def previous(snapshot):
    return copy.deepcopy(snapshot)


def shrink(snap, key, keep):
    snap[key] = snap[key][:keep]
    for name in snap["sources"]:
        if snap["sources"][name]["count"] is not None:
            snap["sources"][name]["count"] = keep
    return snap


def test_no_previous_snapshot_always_passes(snapshot):
    assert evaluate_guard(None, snapshot) == []


def test_identical_snapshot_passes(previous, snapshot):
    assert evaluate_guard(previous, snapshot) == []


def test_empty_owned_rejected(previous, snapshot):
    candidate = shrink(copy.deepcopy(snapshot), "owned", 0)
    reasons = evaluate_guard(previous, candidate, allow_degraded=True)
    assert any("owned became empty" in r for r in reasons)


def test_empty_waitlist_rejected(previous, snapshot):
    candidate = copy.deepcopy(snapshot)
    candidate["waitlisted"] = []
    reasons = evaluate_guard(previous, candidate, allow_degraded=True)
    assert any("waitlisted became empty" in r for r in reasons)


def test_suspicious_shrink_rejected(previous, snapshot):
    previous = copy.deepcopy(previous)
    previous["owned"] = previous["owned"] * 30  # 120 games previously
    candidate = shrink(copy.deepcopy(snapshot), "owned", 3)  # 3 now
    reasons = evaluate_guard(previous, candidate, allow_degraded=True)
    assert any("shrank suspiciously" in r for r in reasons)


def test_small_list_may_shrink_but_not_vanish(previous, snapshot):
    # previous owned = 4 (<= small_list default 10): dropping to 1 is fine
    candidate = shrink(copy.deepcopy(snapshot), "owned", 1)
    assert evaluate_guard(previous, candidate, allow_degraded=True) == []


def test_growth_passes(previous, snapshot):
    candidate = copy.deepcopy(snapshot)
    candidate["owned"] = candidate["owned"] * 3
    assert evaluate_guard(previous, candidate) == []


def test_all_sources_failed_rejected(previous, snapshot):
    candidate = copy.deepcopy(snapshot)
    for src in candidate["sources"].values():
        src["status"] = "error"
        src["count"] = None
    reasons = evaluate_guard(previous, candidate, allow_degraded=True)
    assert any("no source fetched successfully" in r for r in reasons)


def test_degraded_source_rejected_by_default(previous, snapshot):
    candidate = copy.deepcopy(snapshot)
    candidate["sources"]["steam"]["status"] = "error"
    candidate["sources"]["steam"]["count"] = None

    reasons = evaluate_guard(previous, candidate)
    assert any("source 'steam' is error" in r for r in reasons)

    assert evaluate_guard(previous, candidate, allow_degraded=True) == []


def test_degraded_source_ok_if_it_never_contributed(previous, snapshot):
    previous = copy.deepcopy(previous)
    previous["sources"]["steam"]["status"] = "skipped"
    previous["sources"]["steam"]["count"] = None
    candidate = copy.deepcopy(snapshot)
    candidate["sources"]["steam"]["status"] = "skipped"
    candidate["sources"]["steam"]["count"] = None

    assert evaluate_guard(previous, candidate) == []


def test_write_and_reload_roundtrip(tmp_path, snapshot):
    out = tmp_path / "games.json"
    write_snapshot(out, snapshot)

    loaded, warnings = load_previous(out)
    assert warnings == []
    assert loaded == snapshot
    assert out.read_text(encoding="utf-8").endswith("\n")


def test_invalid_snapshot_never_written(tmp_path, snapshot):
    out = tmp_path / "games.json"
    broken = copy.deepcopy(snapshot)
    broken["owned"][0]["title"] = ""  # violates minLength

    with pytest.raises(SnapshotValidationError):
        write_snapshot(out, broken)

    assert not out.exists()
    assert list(tmp_path.iterdir()) == []  # no stray temp files


def test_corrupt_previous_ignored_with_warning(tmp_path):
    out = tmp_path / "games.json"
    out.write_text("{not json", encoding="utf-8")

    loaded, warnings = load_previous(out)
    assert loaded is None
    assert len(warnings) == 1 and "invalid" in warnings[0]


def test_write_rejected_keeps_original(tmp_path, snapshot):
    out = tmp_path / "games.json"
    write_snapshot(out, snapshot)
    before = out.read_text(encoding="utf-8")

    target = write_rejected(out, {"candidate": True}, ["owned became empty"])

    assert target == rejected_path(out)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["rejected_because"] == ["owned became empty"]
    assert out.read_text(encoding="utf-8") == before
