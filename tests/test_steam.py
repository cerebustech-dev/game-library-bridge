import pytest
import responses

from game_library_bridge.sources.steam import OWNED_GAMES_URL, SteamError, fetch_owned_games


@responses.activate
def test_owned_games_parsed(fixture_json):
    responses.get(OWNED_GAMES_URL, json=fixture_json("steam_owned_games.json"))

    games, warnings = fetch_owned_games("FAKEKEY", "76561197970928054")

    assert len(games) == 3
    assert warnings == []
    torchlight = next(g for g in games if g["appid"] == 41500)
    assert torchlight["playtime_forever"] == 341


@responses.activate
def test_private_profile_raises(fixture_json):
    responses.get(OWNED_GAMES_URL, json={"response": {}})

    with pytest.raises(SteamError, match="private"):
        fetch_owned_games("FAKEKEY", "76561197970928054")


@responses.activate
def test_bad_key_message_does_not_leak_key():
    responses.get(OWNED_GAMES_URL, status=403)

    with pytest.raises(SteamError) as excinfo:
        fetch_owned_games("SUPERSECRETKEY", "76561197970928054")

    assert "SUPERSECRETKEY" not in str(excinfo.value)
    assert "STEAM_API_KEY" in str(excinfo.value)


@responses.activate
def test_count_mismatch_warns(fixture_json):
    body = fixture_json("steam_owned_games.json")
    body["response"]["game_count"] = 99
    responses.get(OWNED_GAMES_URL, json=body)

    games, warnings = fetch_owned_games("FAKEKEY", "76561197970928054")

    assert len(games) == 3
    assert any("game_count=99" in w for w in warnings)


@responses.activate
def test_malformed_entry_skipped(fixture_json):
    body = fixture_json("steam_owned_games.json")
    body["response"]["games"].append({"name": "no appid"})
    responses.get(OWNED_GAMES_URL, json=body)

    games, warnings = fetch_owned_games("FAKEKEY", "76561197970928054")

    assert len(games) == 3
    assert any("malformed" in w for w in warnings)
