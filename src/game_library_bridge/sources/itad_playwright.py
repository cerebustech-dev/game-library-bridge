"""Playwright fallback for ITAD extraction.

Used only when the direct JSON endpoints fail (or ITAD_USE_PLAYWRIGHT=1).
Rather than scraping the DOM — which is fragile against markup changes — we
render the real page and intercept the same internal API responses the app
makes itself. That keeps one canonical data shape for both strategies.

Requires the optional extra:  pip install game-library-bridge[browser]
followed by:                  playwright install chromium
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger("glb.itad.playwright")

PAGE_URLS = {
    "itad_collection": "https://isthereanydeal.com/uid/{user}/collection/",
    "itad_waitlist": "https://isthereanydeal.com/uid/{user}/waitlist/",
}
API_MARKERS = {
    "itad_collection": "/collection/api/list/games/",
    "itad_waitlist": "/waitlist/api/list/games/",
}


class PlaywrightUnavailable(RuntimeError):
    pass


def fetch_via_playwright(user: str, source: str, timeout_ms: int = 45000) -> tuple[list[dict], list[str]]:
    """Render the public page and capture the app's own list-API responses.

    Returns (games, warnings); source is "itad_collection" or "itad_waitlist".
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise PlaywrightUnavailable(
            "playwright is not installed; run: pip install game-library-bridge[browser] "
            "&& playwright install chromium"
        ) from exc

    marker = API_MARKERS[source]
    url = PAGE_URLS[source].format(user=user)
    captured: list[dict] = []
    warnings: list[str] = []

    def on_response(response) -> None:
        if marker not in response.url:
            return
        try:
            payload = response.json()
        except Exception:
            warnings.append(f"{source}: non-JSON API response captured from {response.url}")
            return
        captured.append(payload)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.on("response", on_response)
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        finally:
            browser.close()

    games: list[dict] = []
    for payload in captured:
        if isinstance(payload, dict) and "games" in payload and isinstance(payload["games"], dict):
            games.extend(payload["games"].values())  # waitlist shape
        elif isinstance(payload, dict):
            games.extend(payload.values())  # collection shape (flat map)
        elif isinstance(payload, list) and payload:
            warnings.append(f"{source}: unexpected array payload: {json.dumps(payload)[:120]}")

    valid = [
        g
        for g in games
        if isinstance(g, dict) and isinstance(g.get("id"), str) and (g.get("title") or "").strip()
    ]
    skipped = len(games) - len(valid)
    if skipped:
        warnings.append(f"{source}: playwright capture skipped {skipped} malformed entries")
    if not captured:
        warnings.append(f"{source}: playwright rendered the page but captured no API responses")

    log.info("playwright capture complete", extra={"source": source, "count": len(valid)})
    return valid, warnings
