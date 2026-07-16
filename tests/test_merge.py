from game_library_bridge.merge import build_snapshot
from game_library_bridge.models import (
    SOURCE_ITAD_COLLECTION,
    SOURCE_STEAM,
    STATUS_ERROR,
    FetchResult,
)


def owned_by_title(snapshot, title):
    return next(e for e in snapshot["owned"] if e["title"] == title)


def test_cross_source_match_by_normalized_title(snapshot):
    entry = owned_by_title(snapshot, "Mass Effect™ Legendary Edition")
    assert entry["sources"] == [SOURCE_STEAM, SOURCE_ITAD_COLLECTION]
    assert entry["steam_appid"] == 1328670
    assert entry["itad_id"] == "018d937e-ffff-720c-9024-4983cebd0001"


def test_steam_playtime_wins_and_itad_fills_gaps(snapshot):
    merged = owned_by_title(snapshot, "Torchlight")
    assert merged["playtime_minutes"] == 341  # both agree here, from steam

    itad_only = owned_by_title(snapshot, "ITAD Only Gem")
    assert itad_only["sources"] == [SOURCE_ITAD_COLLECTION]
    assert itad_only["steam_appid"] is None
    assert itad_only["playtime_minutes"] == 45  # itad minutes used as fallback


def test_owned_is_union_of_sources(snapshot):
    # 3 steam games all matched by ITAD + 1 ITAD-only = 4
    assert len(snapshot["owned"]) == 4
    assert all(e["sources"] for e in snapshot["owned"])


def test_waitlist_entries(snapshot):
    assert [e["title"] for e in snapshot["waitlisted"]] == [
        "GRAVEN",
        "Hollow Knight: Silksong",
    ]
    graven = snapshot["waitlisted"][0]
    assert graven["sources"] == ["itad_waitlist"]
    assert graven["itad_slug"] == "graven"
    assert graven["added_at"].endswith("Z")
    assert "playtime_minutes" not in graven


def test_provenance_and_counts(snapshot):
    assert snapshot["sources"]["steam"]["status"] == "ok"
    assert snapshot["sources"]["steam"]["count"] == 3
    assert snapshot["sources"]["itad_collection"]["count"] == 4
    assert snapshot["sources"]["itad_waitlist"]["count"] == 2
    assert snapshot["identity"] == {"steam_id": "76561197970928054", "itad_user": "arcca"}


def test_failed_source_recorded_in_warnings(ok_results):
    steam, coll, wait = ok_results
    broken = FetchResult(SOURCE_STEAM, status=STATUS_ERROR, error="boom")

    snap = build_snapshot(
        broken, coll, wait, steam_id="1" * 17, itad_user="arcca", previous=None
    )

    assert snap["sources"]["steam"]["status"] == "error"
    assert snap["sources"]["steam"]["count"] is None
    assert any("steam: not fetched" in w for w in snap["warnings"])
    # owned falls back to ITAD collection only
    assert len(snap["owned"]) == 4
    assert all(e["steam_appid"] is None for e in snap["owned"])


def test_snapshot_version_increments(ok_results):
    steam, coll, wait = ok_results
    first = build_snapshot(steam, coll, wait, steam_id="1" * 17, itad_user="a", previous=None)
    second = build_snapshot(steam, coll, wait, steam_id="1" * 17, itad_user="a", previous=first)

    assert first["snapshot_version"] == 1
    assert second["snapshot_version"] == 2


def test_duplicate_steam_titles_warn(ok_results):
    steam, coll, wait = ok_results
    dupe = dict(steam.games[0], appid=99999)
    steam_with_dupe = FetchResult(
        SOURCE_STEAM, games=[*steam.games, dupe], fetched_at=steam.fetched_at, via="test"
    )

    snap = build_snapshot(
        steam_with_dupe, coll, wait, steam_id="1" * 17, itad_user="a", previous=None
    )

    assert any("duplicate normalized title" in w for w in snap["warnings"])
    assert len(snap["owned"]) == 5
