# Publishing games.json through GitHub Pages

Goal: a stable public URL like

```
https://<username>.github.io/game-library-bridge/games.json
```

that always serves the latest valid snapshot.

## One-time setup

1. **Create the GitHub repository** and push this project:

   ```bash
   cd game-library-bridge
   git init -b main
   git add .
   git commit -m "feat: initial game-library-bridge"
   gh repo create game-library-bridge --public --source . --push
   ```

2. **Add the Steam API key as a secret** (never commit it):

   ```bash
   gh secret set STEAM_API_KEY
   ```

   Or in the UI: *Settings → Secrets and variables → Actions → New repository
   secret*, name `STEAM_API_KEY`. Get a key at
   <https://steamcommunity.com/dev/apikey>.

3. **Enable GitHub Pages via Actions**: *Settings → Pages → Build and
   deployment → Source: GitHub Actions*. No branch configuration needed —
   `pages.yml` deploys the `public/` directory through the official
   `upload-pages-artifact` / `deploy-pages` actions.

4. **Allow the refresh workflow to push**: *Settings → Actions → General →
   Workflow permissions → Read and write permissions*. (The workflow also
   declares `permissions: contents: write` explicitly.)

5. **Seed the first snapshot** (locally, so the guard has a baseline and the
   site isn't empty until the first cron run):

   ```bash
   uv run python -m game_library_bridge
   git add public/games.json
   git commit -m "chore: seed initial snapshot"
   git push
   ```

## How the pipeline flows after that

```
cron (daily 05:17 UTC)
  └─ refresh.yml: fetch Steam + ITAD → merge → schema-validate → guard
       ├─ guard OK  → commit public/games.json if changed → push to main
       │              → deploy public/ to GitHub Pages (same workflow)
       └─ guard REJECTS → job fails (exit 2), previous snapshot stays,
                          nothing is deployed
             └─ games.rejected.json uploaded as a workflow artifact
```

`refresh.yml` deploys Pages itself because commits pushed with the default
`GITHUB_TOKEN` intentionally do **not** trigger other workflows — a
`paths: public/**` push trigger alone would never fire for the bot's commits.
`pages.yml` still covers the cases that do trigger on push: snapshots you
commit yourself (e.g. the seed below) and manual `workflow_dispatch`.

You can also trigger either workflow manually from the *Actions* tab
(`workflow_dispatch`).

## Consuming the JSON

```bash
curl -s https://<username>.github.io/game-library-bridge/games.json | jq '.owned | length'
```

Consumers should pin on `schema_version` (semver of the document format) and
can use `snapshot_version` / `generated_at` to detect updates. GitHub Pages
sends sensible caching headers (`max-age=600`), so clients see updates within
minutes of a deploy.

## Notes & caveats

- **Steam profile privacy**: the SteamID's *Game details* must be public, or
  the Steam API returns an empty response and the source is recorded as
  `error` (the guard then protects the previous snapshot).
- **ITAD endpoints are internal**: they were verified working (2026-07) but are
  not a documented contract. If they change shape, the run fails safe; install
  the Playwright fallback (`uv sync --extra browser && uv run playwright
  install chromium`) or set `ITAD_USE_PLAYWRIGHT=1`. In Actions you would add
  those two commands to `refresh.yml` before the build step.
- **Custom domain / different repo name**: only the URL prefix changes; the
  workflows don't care.
- **Rate limits**: one page-load plus a handful of JSON POSTs per day is well
  within polite use of ITAD; the Steam Web API allows 100k calls/day.
