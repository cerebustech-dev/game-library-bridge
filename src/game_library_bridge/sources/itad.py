"""IsThereAnyDeal public-profile client.

ITAD's public collection/waitlist pages are a Svelte SPA whose shell embeds an
anonymous session token; the game lists are then fetched from internal JSON
endpoints. We replay exactly that flow (verified 2026-07):

  1. GET  https://isthereanydeal.com/uid/<user>/collection/
     -> HTML containing  "token":"<ITAD-SessionToken>"  in an inline config,
        plus session cookies.
  2. POST /collection/api/list/games/   body {"user": <user>, "page": N}
     -> {"<itad-uuid>": {id, slug, title, playtime (minutes), added, ...}, ...}
        An empty page returns [] — that terminates pagination (~5000/page).
  3. POST /waitlist/api/list/games/     body {"user": <user>, "page": N}
     -> {"hasNext": bool, "games": {<itad-uuid>: {...}}}

Headers: Content-Type/Accept application/json + ITAD-SessionToken.
These endpoints are internal, not the documented api.isthereanydeal.com API,
so shape changes are possible — hence strict response validation and the
Playwright fallback in itad_playwright.py.
"""

from __future__ import annotations

import logging
import re

import requests

log = logging.getLogger("glb.itad")

BASE_URL = "https://isthereanydeal.com"
COLLECTION_API = "/collection/api/list/games/"
WAITLIST_API = "/waitlist/api/list/games/"
USER_AGENT = "game-library-bridge/0.1 (+https://github.com/; personal library export)"

# Token as it appears in the SSR inline config: "token":"5Doxwt..."
_TOKEN_RE = re.compile(r'"token"\s*:\s*"([A-Za-z0-9_\-.]+)"')

MAX_PAGES = 200  # safety cap; a real library fits in a handful of pages


class ItadError(RuntimeError):
    pass


class ItadClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        session: requests.Session | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.timeout = timeout
        self._token: str | None = None

    # -- session token ---------------------------------------------------

    def _mint_token(self, user: str, kind: str) -> str:
        url = f"{self.base_url}/uid/{user}/{kind}/"
        try:
            resp = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ItadError(f"failed to load ITAD page {url}: {exc.__class__.__name__}") from exc
        if resp.status_code == 404:
            raise ItadError(f"ITAD profile page not found: {url} (is ITAD_USER correct and public?)")
        if resp.status_code != 200:
            raise ItadError(f"ITAD page {url} returned HTTP {resp.status_code}")
        match = _TOKEN_RE.search(resp.text)
        if not match:
            raise ItadError(
                "no session token found in ITAD page HTML; the frontend layout may "
                "have changed (consider ITAD_USE_PLAYWRIGHT=1)"
            )
        self._token = match.group(1)
        log.debug("minted anonymous ITAD session token")
        return self._token

    def _ensure_token(self, user: str, kind: str) -> str:
        return self._token or self._mint_token(user, kind)

    # -- API calls ---------------------------------------------------------

    def _api_post(self, path: str, payload: dict, user: str, kind: str):
        token = self._ensure_token(user, kind)
        url = f"{self.base_url}{path}"
        for attempt in (1, 2):
            try:
                resp = self.session.post(
                    url,
                    json=payload,
                    headers={"Accept": "application/json", "ITAD-SessionToken": token},
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise ItadError(f"ITAD API request to {path} failed: {exc.__class__.__name__}") from exc
            if resp.status_code in (400, 401, 403) and attempt == 1:
                # Token may have expired mid-run; mint a fresh one and retry once.
                log.debug("ITAD API returned %s; re-minting token", resp.status_code)
                token = self._mint_token(user, kind)
                continue
            break
        if resp.status_code != 200:
            raise ItadError(f"ITAD API {path} returned HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise ItadError(f"ITAD API {path} returned non-JSON body") from exc

    # -- public fetchers ----------------------------------------------------

    def fetch_collection(self, user: str) -> tuple[list[dict], list[str]]:
        """All games in the public collection. Returns (games, warnings)."""
        games: list[dict] = []
        warnings: list[str] = []
        for page in range(MAX_PAGES):
            data = self._api_post(COLLECTION_API, {"user": user, "page": page}, user, "collection")
            if isinstance(data, list):
                if data:
                    raise ItadError("collection endpoint returned a non-empty array; shape changed")
                break  # empty page -> done
            if not isinstance(data, dict):
                raise ItadError(f"unexpected collection response type: {type(data).__name__}")
            if not data:
                break
            games.extend(_validated_games(data.values(), "itad_collection", warnings))
            log.debug("collection page fetched", extra={"page": page, "total": len(games)})
        else:
            warnings.append(f"itad_collection: stopped at pagination cap of {MAX_PAGES} pages")
        log.info("fetched itad collection", extra={"count": len(games)})
        return games, warnings

    def fetch_waitlist(self, user: str) -> tuple[list[dict], list[str]]:
        """All games on the public waitlist. Returns (games, warnings)."""
        games: list[dict] = []
        warnings: list[str] = []
        page = 0
        while page < MAX_PAGES:
            data = self._api_post(WAITLIST_API, {"user": user, "page": page}, user, "waitlist")
            if not isinstance(data, dict) or "games" not in data:
                raise ItadError("unexpected waitlist response shape (no 'games' key)")
            batch = data["games"]
            if not isinstance(batch, dict):
                raise ItadError(f"unexpected waitlist games type: {type(batch).__name__}")
            games.extend(_validated_games(batch.values(), "itad_waitlist", warnings))
            if not data.get("hasNext"):
                break
            page += 1
        else:
            warnings.append(f"itad_waitlist: stopped at pagination cap of {MAX_PAGES} pages")
        log.info("fetched itad waitlist", extra={"count": len(games)})
        return games, warnings


def _validated_games(raw_games, source: str, warnings: list[str]) -> list[dict]:
    valid = []
    for raw in raw_games:
        if (
            isinstance(raw, dict)
            and isinstance(raw.get("id"), str)
            and isinstance(raw.get("title"), str)
            and raw["title"].strip()
        ):
            valid.append(raw)
        else:
            warnings.append(f"{source}: skipped malformed entry: {str(raw)[:120]}")
    return valid
