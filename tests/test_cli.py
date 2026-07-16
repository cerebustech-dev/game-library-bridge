"""End-to-end runs of the CLI against fully mocked HTTP."""

import json

import pytest
import responses

from game_library_bridge.__main__ import run
from game_library_bridge.sources.itad import BASE_URL, COLLECTION_API, WAITLIST_API
from game_library_bridge.sources.steam import OWNED_GAMES_URL


@pytest.fixture(autouse=True)
def env(monkeypatch):
    # Keep a developer's real .env out of the tests.
    monkeypatch.setattr("game_library_bridge.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("GUARD_MIN_RATIO", "0.5")
    monkeypatch.setenv("GUARD_SMALL_LIST", "10")
    monkeypatch.setenv("STEAM_API_KEY", "FAKEKEY")
    monkeypatch.setenv("STEAM_ID", "76561197970928054")
    monkeypatch.setenv("ITAD_USER", "arcca")
    monkeypatch.setenv("ITAD_USE_PLAYWRIGHT", "0")
    monkeypatch.setenv("LOG_FORMAT", "text")


def mock_happy_path(rsps, fixture_text, fixture_json):
    rsps.get(OWNED_GAMES_URL, json=fixture_json("steam_owned_games.json"))
    rsps.get(f"{BASE_URL}/uid/arcca/collection/", body=fixture_text("itad_page.html"))
    rsps.post(f"{BASE_URL}{COLLECTION_API}", json=fixture_json("itad_collection_page0.json"))
    rsps.post(f"{BASE_URL}{COLLECTION_API}", json=[])
    rsps.post(f"{BASE_URL}{WAITLIST_API}", json=fixture_json("itad_waitlist_page0.json"))
    rsps.post(f"{BASE_URL}{WAITLIST_API}", json=fixture_json("itad_waitlist_page1.json"))


@responses.activate
def test_full_run_writes_valid_snapshot(tmp_path, fixture_text, fixture_json):
    mock_happy_path(responses, fixture_text, fixture_json)
    out = tmp_path / "games.json"

    assert run(["--output", str(out)]) == 0

    snap = json.loads(out.read_text(encoding="utf-8"))
    assert snap["snapshot_version"] == 1
    assert len(snap["owned"]) == 4
    assert len(snap["waitlisted"]) == 2
    assert snap["sources"]["steam"]["via"] == "steam-web-api"
    assert snap["sources"]["itad_collection"]["via"] == "json-api"


@responses.activate
def test_second_run_bumps_version(tmp_path, fixture_text, fixture_json):
    mock_happy_path(responses, fixture_text, fixture_json)
    out = tmp_path / "games.json"
    assert run(["--output", str(out)]) == 0

    mock_happy_path(responses, fixture_text, fixture_json)
    assert run(["--output", str(out)]) == 0

    snap = json.loads(out.read_text(encoding="utf-8"))
    assert snap["snapshot_version"] == 2


@responses.activate
def test_guard_blocks_empty_refetch_and_keeps_previous(tmp_path, fixture_text, fixture_json):
    mock_happy_path(responses, fixture_text, fixture_json)
    out = tmp_path / "games.json"
    assert run(["--output", str(out)]) == 0
    before = out.read_text(encoding="utf-8")

    # Second run: everything comes back empty (e.g. upstream regression).
    responses.get(OWNED_GAMES_URL, json={"response": {"game_count": 0, "games": []}})
    responses.get(f"{BASE_URL}/uid/arcca/collection/", body=fixture_text("itad_page.html"))
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=[])
    responses.post(f"{BASE_URL}{WAITLIST_API}", json={"hasNext": False, "games": {}})

    assert run(["--output", str(out)]) == 2

    assert out.read_text(encoding="utf-8") == before  # previous snapshot intact
    rejected = json.loads((tmp_path / "games.rejected.json").read_text(encoding="utf-8"))
    assert any("became empty" in r for r in rejected["rejected_because"])


@responses.activate
def test_degraded_steam_blocks_unless_allowed(tmp_path, fixture_text, fixture_json):
    mock_happy_path(responses, fixture_text, fixture_json)
    out = tmp_path / "games.json"
    assert run(["--output", str(out)]) == 0

    def mock_steam_down():
        responses.get(OWNED_GAMES_URL, status=500)
        responses.get(f"{BASE_URL}/uid/arcca/collection/", body=fixture_text("itad_page.html"))
        responses.post(f"{BASE_URL}{COLLECTION_API}", json=fixture_json("itad_collection_page0.json"))
        responses.post(f"{BASE_URL}{COLLECTION_API}", json=[])
        responses.post(f"{BASE_URL}{WAITLIST_API}", json=fixture_json("itad_waitlist_page0.json"))
        responses.post(f"{BASE_URL}{WAITLIST_API}", json=fixture_json("itad_waitlist_page1.json"))

    mock_steam_down()
    assert run(["--output", str(out)]) == 2

    mock_steam_down()
    assert run(["--output", str(out), "--allow-degraded"]) == 0

    snap = json.loads(out.read_text(encoding="utf-8"))
    assert snap["sources"]["steam"]["status"] == "error"
    assert len(snap["owned"]) == 4  # ITAD collection still covers the library


@responses.activate
def test_dry_run_writes_nothing(tmp_path, fixture_text, fixture_json):
    mock_happy_path(responses, fixture_text, fixture_json)
    out = tmp_path / "games.json"

    assert run(["--output", str(out), "--dry-run"]) == 0

    assert not out.exists()


@responses.activate
def test_dry_run_reports_guard_rejection_without_writing(tmp_path, fixture_text, fixture_json):
    mock_happy_path(responses, fixture_text, fixture_json)
    out = tmp_path / "games.json"
    assert run(["--output", str(out)]) == 0
    before = out.read_text(encoding="utf-8")

    responses.get(OWNED_GAMES_URL, json={"response": {"game_count": 0, "games": []}})
    responses.get(f"{BASE_URL}/uid/arcca/collection/", body=fixture_text("itad_page.html"))
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=[])
    responses.post(f"{BASE_URL}{WAITLIST_API}", json={"hasNext": False, "games": {}})

    assert run(["--output", str(out), "--dry-run"]) == 2

    assert out.read_text(encoding="utf-8") == before
    assert not (tmp_path / "games.rejected.json").exists()


@responses.activate
def test_missing_steam_key_is_skipped_not_fatal(tmp_path, monkeypatch, fixture_text, fixture_json):
    monkeypatch.delenv("STEAM_API_KEY")
    responses.get(f"{BASE_URL}/uid/arcca/collection/", body=fixture_text("itad_page.html"))
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=fixture_json("itad_collection_page0.json"))
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=[])
    responses.post(f"{BASE_URL}{WAITLIST_API}", json=fixture_json("itad_waitlist_page0.json"))
    responses.post(f"{BASE_URL}{WAITLIST_API}", json=fixture_json("itad_waitlist_page1.json"))
    out = tmp_path / "games.json"

    assert run(["--output", str(out)]) == 0

    snap = json.loads(out.read_text(encoding="utf-8"))
    assert snap["sources"]["steam"]["status"] == "skipped"
    assert any("STEAM_API_KEY" in w for w in snap["warnings"])
