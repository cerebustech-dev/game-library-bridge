from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text():
    def _load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _load


@pytest.fixture
def fixture_json():
    def _load(name: str):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def ok_results(fixture_json):
    """FetchResults for all three sources, as a successful run would produce."""
    from game_library_bridge.models import (
        SOURCE_ITAD_COLLECTION,
        SOURCE_ITAD_WAITLIST,
        SOURCE_STEAM,
        FetchResult,
    )

    steam_games = fixture_json("steam_owned_games.json")["response"]["games"]
    coll_games = list(fixture_json("itad_collection_page0.json").values())
    wait_games = list(fixture_json("itad_waitlist_page0.json")["games"].values()) + list(
        fixture_json("itad_waitlist_page1.json")["games"].values()
    )
    ts = "2026-07-16T00:00:00Z"
    return (
        FetchResult(SOURCE_STEAM, games=steam_games, fetched_at=ts, via="steam-web-api"),
        FetchResult(SOURCE_ITAD_COLLECTION, games=coll_games, fetched_at=ts, via="json-api"),
        FetchResult(SOURCE_ITAD_WAITLIST, games=wait_games, fetched_at=ts, via="json-api"),
    )


@pytest.fixture
def snapshot(ok_results):
    from game_library_bridge.merge import build_snapshot

    steam, coll, wait = ok_results
    return build_snapshot(
        steam, coll, wait,
        steam_id="76561197970928054",
        itad_user="arcca",
        previous=None,
        generated_at="2026-07-16T00:00:00Z",
    )
