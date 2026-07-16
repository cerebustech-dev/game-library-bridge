# game-library-bridge

Produces a **stable, public, machine-readable snapshot** (`games.json`) of PC game
ownership and wishlist, merged from:

| Source | What it provides | How it's fetched |
|---|---|---|
| Steam Web API | Owned games + playtime for a SteamID | `IPlayerService/GetOwnedGames` (needs `STEAM_API_KEY`) |
| ITAD Collection | Public collection at `isthereanydeal.com/uid/<user>/collection/` | Internal JSON endpoints (see below), Playwright fallback |
| ITAD Waitlist | Public waitlist at `isthereanydeal.com/uid/<user>/waitlist/` | Same |

## How ITAD extraction works

ITAD's public profile pages are a Svelte SPA. Investigation of the rendered pages
showed they call **accessible internal JSON endpoints**, so no DOM scraping is
needed:

1. `GET /uid/<user>/collection/` — the HTML shell embeds an anonymous session
   token (`"token":"..."` in an inline config) and sets session cookies.
2. `POST /collection/api/list/games/` with body `{"user": "<user>", "page": N}`
   and header `ITAD-SessionToken: <token>` — returns a map of games (including
   per-game `playtime` in minutes and `added` timestamps). An empty page
   returns `[]`, which ends pagination.
3. `POST /waitlist/api/list/games/` — same, but returns `{"hasNext": bool, "games": {...}}`.

These endpoints are *internal* (not the documented `api.isthereanydeal.com` API),
so responses are strictly validated and a **Playwright fallback** exists: it
renders the real page and intercepts the same API responses the app makes
(no fragile DOM selectors). Enable it with `ITAD_USE_PLAYWRIGHT=1` after
installing the `browser` extra; it also engages automatically if the direct
endpoints fail and Playwright is installed.

## Quick start

```bash
cd game-library-bridge
uv sync --group dev          # or: pip install -e . && pip install pytest responses
cp .env.example .env         # fill in STEAM_API_KEY (never committed)
uv run pytest                # run the test suite
uv run python -m game_library_bridge --dry-run   # fetch + validate, write nothing
uv run python -m game_library_bridge             # write public/games.json
```

Optional Playwright fallback:

```bash
uv sync --group dev --extra browser
uv run playwright install chromium
```

### CLI

```
game-library-bridge [--output PATH] [--dry-run] [--force]
                    [--allow-degraded] [--skip-steam] [--skip-itad]
```

Exit codes: `0` success, `2` snapshot guard rejected the candidate (previous
snapshot kept), `1` unexpected error.

## The snapshot (`public/games.json`)

Versioned and schema-validated (`src/game_library_bridge/schemas/games.schema.json`,
JSON Schema 2020-12). Top-level shape:

```jsonc
{
  "schema_version": "1.0.0",     // document format version (semver)
  "snapshot_version": 42,        // monotonically increasing per successful write
  "generated_at": "2026-07-16T05:17:03Z",
  "identity": { "steam_id": "76561197970928054", "itad_user": "arcca" },
  "sources": {                   // per-source provenance
    "steam":           { "status": "ok", "fetched_at": "...", "count": 300, "via": "steam-web-api", "error": null },
    "itad_collection": { "status": "ok", "fetched_at": "...", "count": 108, "via": "json-api", "error": null },
    "itad_waitlist":   { "status": "ok", "fetched_at": "...", "count": 9,   "via": "json-api", "error": null }
  },
  "owned": [
    {
      "title": "Baldur's Gate 3",
      "normalized_title": "baldur s gate 3",
      "steam_appid": 1086940,          // null if only seen on ITAD
      "itad_id": "018d...uuid",        // null if only seen on Steam
      "itad_slug": "baldurs-gate-iii",
      "playtime_minutes": 14068,       // Steam wins; ITAD (also minutes) fills gaps
      "added_at": "2026-07-14T14:26:48Z",
      "sources": ["steam", "itad_collection"]
    }
  ],
  "waitlisted": [
    {
      "title": "Hollow Knight: Silksong",
      "normalized_title": "hollow knight silksong",
      "itad_id": "018d...uuid",
      "itad_slug": "hollow-knight-silksong",
      "added_at": "2026-07-14T14:29:59Z",
      "sources": ["itad_waitlist"]
    }
  ],
  "warnings": ["itad_collection: skipped malformed entry: ..."]
}
```

Cross-source identity is matched by **normalized title** (lowercase, ASCII-fold,
punctuation stripped) because ITAD's internal ids don't expose Steam appids.
Unmatched entries are kept from both sides; anomalies land in `warnings`.

## Snapshot guard

A valid previous snapshot is **never overwritten** with empty or suspiciously
incomplete data. A candidate is rejected when:

- no source fetched successfully, or
- `owned`/`waitlisted` became empty while previously non-empty, or
- a list shrank below `GUARD_MIN_RATIO` (default 50%) of the previous size
  (lists of ≤ `GUARD_SMALL_LIST` entries only guard against becoming empty), or
- a source that previously contributed games failed this run
  (override per-run with `--allow-degraded`).

On rejection the run exits `2`, keeps the previous snapshot, and writes the
candidate plus reasons to `public/games.rejected.json` for inspection.
`--force` bypasses the guard (the override is recorded in `warnings`).

Writes are atomic (temp file + rename), and every snapshot is validated against
the schema before it touches disk.

## Configuration

All via environment variables / `.env` — see [.env.example](.env.example).
**Secrets:** only `STEAM_API_KEY`. It lives in `.env` locally (gitignored) and
in the `STEAM_API_KEY` repository secret on GitHub. It is sent only to
`api.steampowered.com` as a query parameter and is redacted from error messages.

## Scheduled refresh & publishing

- [`.github/workflows/ci.yml`](.github/workflows/ci.yml) — tests on every push/PR.
- [`.github/workflows/refresh.yml`](.github/workflows/refresh.yml) — daily
  scheduled rebuild; commits `public/games.json` when it changed; fails loudly
  (and uploads the rejected candidate as an artifact) when the guard trips.
- [`.github/workflows/pages.yml`](.github/workflows/pages.yml) — publishes
  `public/` to GitHub Pages whenever the snapshot changes on `main`.

Full publishing setup: [docs/publishing.md](docs/publishing.md).

## Project layout

```
src/game_library_bridge/
  __main__.py          CLI + orchestration (fetch -> merge -> guard -> write)
  config.py            env/.env settings
  logging_setup.py     structured logging (json | text)
  models.py            FetchResult, title normalization, time helpers
  merge.py             cross-source merge into the snapshot document
  schema.py            JSON Schema validation
  schemas/games.schema.json
  snapshot.py          atomic writes, previous-snapshot loading, overwrite guard
  sources/steam.py     Steam Web API client
  sources/itad.py      ITAD internal JSON API client
  sources/itad_playwright.py  render-and-intercept fallback
tests/                 pytest suite, fully offline (mocked HTTP)
public/                snapshot output, served by GitHub Pages
```
