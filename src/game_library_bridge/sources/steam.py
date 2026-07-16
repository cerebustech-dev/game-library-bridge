"""Steam Web API client for owned games + playtime.

Uses IPlayerService/GetOwnedGames (official Web API, requires an API key).
The old keyless community XML endpoint (games?tab=all&xml=1) now redirects to
a login page, so a key is the only supported path.
"""

from __future__ import annotations

import logging

import requests

log = logging.getLogger("glb.steam")

OWNED_GAMES_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"


class SteamError(RuntimeError):
    pass


def fetch_owned_games(
    api_key: str,
    steam_id: str,
    session: requests.Session | None = None,
    timeout: float = 30.0,
) -> tuple[list[dict], list[str]]:
    """Return (raw game dicts, warnings). Raises SteamError on failure.

    Each raw game keeps Steam's shape: {"appid": int, "name": str,
    "playtime_forever": int (minutes), ...}.
    """
    sess = session or requests.Session()
    params = {
        "key": api_key,
        "steamid": steam_id,
        "include_appinfo": 1,
        "include_played_free_games": 1,
        "format": "json",
    }
    try:
        resp = sess.get(OWNED_GAMES_URL, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise SteamError(f"Steam API request failed: {exc.__class__.__name__}") from exc

    if resp.status_code in (401, 403):
        # Never echo the key or the full URL (the key is a query param).
        raise SteamError(f"Steam API rejected the request (HTTP {resp.status_code}); check STEAM_API_KEY")
    if resp.status_code != 200:
        raise SteamError(f"Steam API returned HTTP {resp.status_code}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise SteamError("Steam API returned non-JSON body") from exc

    response = body.get("response")
    if not isinstance(response, dict) or "games" not in response:
        # Steam returns {"response": {}} for private profiles / bad steamids.
        raise SteamError(
            "Steam API returned no games list; profile game details may be private "
            f"or STEAM_ID={steam_id} is wrong"
        )

    games: list[dict] = []
    warnings: list[str] = []
    for raw in response["games"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("appid"), int):
            warnings.append(f"steam: skipped malformed entry: {str(raw)[:120]}")
            continue
        if not (raw.get("name") or "").strip():
            warnings.append(f"steam: appid {raw['appid']} has no name; kept with placeholder")
            raw = {**raw, "name": f"steam-app-{raw['appid']}"}
        games.append(raw)

    declared = response.get("game_count")
    if isinstance(declared, int) and declared != len(games):
        warnings.append(
            f"steam: game_count={declared} but parsed {len(games)} entries"
        )

    log.info("fetched steam owned games", extra={"count": len(games)})
    return games, warnings
