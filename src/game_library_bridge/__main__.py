"""CLI entry point: fetch all sources, merge, guard, write games.json.

Exit codes:
  0 - snapshot written (or --dry-run completed)
  2 - candidate rejected by the snapshot guard; previous snapshot kept
  1 - unexpected failure
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import Settings
from .logging_setup import setup_logging
from .merge import build_snapshot
from .models import (
    SOURCE_ITAD_COLLECTION,
    SOURCE_ITAD_WAITLIST,
    SOURCE_STEAM,
    STATUS_ERROR,
    STATUS_SKIPPED,
    FetchResult,
    utc_now_iso,
)
from .snapshot import evaluate_guard, load_previous, write_rejected, write_snapshot
from .sources.itad import ItadClient, ItadError
from .sources.steam import SteamError, fetch_owned_games

log = logging.getLogger("glb.runner")


def _fetch_steam(settings: Settings, skip: bool) -> FetchResult:
    if skip:
        return FetchResult(SOURCE_STEAM, status=STATUS_SKIPPED, error="skipped by flag")
    if not settings.steam_api_key:
        return FetchResult(
            SOURCE_STEAM,
            status=STATUS_SKIPPED,
            error="STEAM_API_KEY is not set (see .env.example)",
        )
    try:
        games, warnings = fetch_owned_games(
            settings.steam_api_key, settings.steam_id, timeout=settings.http_timeout
        )
        return FetchResult(
            SOURCE_STEAM,
            games=games,
            warnings=warnings,
            fetched_at=utc_now_iso(),
            via="steam-web-api",
        )
    except SteamError as exc:
        log.error("steam fetch failed", extra={"error": str(exc)})
        return FetchResult(SOURCE_STEAM, status=STATUS_ERROR, error=str(exc))


def _fetch_itad(source: str, settings: Settings, client: ItadClient, skip: bool) -> FetchResult:
    if skip:
        return FetchResult(source, status=STATUS_SKIPPED, error="skipped by flag")

    fetchers = {
        SOURCE_ITAD_COLLECTION: client.fetch_collection,
        SOURCE_ITAD_WAITLIST: client.fetch_waitlist,
    }
    direct_error: str | None = None

    if not settings.itad_use_playwright:
        try:
            games, warnings = fetchers[source](settings.itad_user)
            return FetchResult(
                source, games=games, warnings=warnings, fetched_at=utc_now_iso(), via="json-api"
            )
        except ItadError as exc:
            direct_error = str(exc)
            log.warning(
                "itad direct fetch failed; trying playwright fallback",
                extra={"source": source, "error": direct_error},
            )

    try:
        from .sources.itad_playwright import PlaywrightUnavailable, fetch_via_playwright

        try:
            games, warnings = fetch_via_playwright(settings.itad_user, source)
            if direct_error:
                warnings = [f"{source}: direct JSON endpoint failed ({direct_error}); "
                            f"used playwright fallback", *warnings]
            return FetchResult(
                source, games=games, warnings=warnings, fetched_at=utc_now_iso(), via="playwright"
            )
        except PlaywrightUnavailable as exc:
            error = direct_error or "playwright requested but unavailable"
            log.error(
                "itad fetch failed and playwright is unavailable",
                extra={"source": source, "error": str(exc)},
            )
            return FetchResult(source, status=STATUS_ERROR, error=f"{error}; {exc}")
    except Exception as exc:  # playwright runtime errors must not kill the run
        log.error("itad playwright fallback failed", extra={"source": source, "error": str(exc)})
        combined = f"direct: {direct_error}; playwright: {exc}" if direct_error else str(exc)
        return FetchResult(source, status=STATUS_ERROR, error=combined)


def _content_unchanged(previous: dict | None, candidate: dict) -> bool:
    """True when writing would change nothing but run metadata.

    Requires matching schema_version too: a document-format upgrade must be
    republished even if the library content is identical.
    """
    return (
        previous is not None
        and previous.get("schema_version") == candidate["schema_version"]
        and previous.get("content_hash") is not None
        and previous.get("content_hash") == candidate["content_hash"]
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="game-library-bridge",
        description="Produce a versioned games.json snapshot from Steam and IsThereAnyDeal.",
    )
    parser.add_argument("--output", type=Path, default=None, help="output path (default: OUTPUT_PATH env or public/games.json)")
    parser.add_argument("--dry-run", action="store_true", help="fetch and validate but write nothing")
    parser.add_argument("--force", action="store_true", help="write even if the snapshot guard objects or the content is unchanged")
    parser.add_argument("--allow-degraded", action="store_true", help="allow writing when a previously-contributing source failed")
    parser.add_argument("--skip-steam", action="store_true", help="do not fetch Steam")
    parser.add_argument("--skip-itad", action="store_true", help="do not fetch ITAD collection/waitlist")
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings.from_env()
    setup_logging(settings.log_level, settings.log_format)
    output = args.output or settings.output_path

    log.info(
        "starting refresh",
        extra={
            "steam_id": settings.steam_id,
            "itad_user": settings.itad_user,
            "output": str(output),
            "dry_run": args.dry_run,
        },
    )

    steam = _fetch_steam(settings, skip=args.skip_steam)
    client = ItadClient(timeout=settings.http_timeout)
    collection = _fetch_itad(SOURCE_ITAD_COLLECTION, settings, client, skip=args.skip_itad)
    waitlist = _fetch_itad(SOURCE_ITAD_WAITLIST, settings, client, skip=args.skip_itad)

    previous, prev_warnings = load_previous(output)
    candidate = build_snapshot(
        steam, collection, waitlist,
        steam_id=settings.steam_id,
        itad_user=settings.itad_user,
        previous=previous,
    )
    candidate["warnings"].extend(prev_warnings)

    reasons = evaluate_guard(
        previous,
        candidate,
        min_ratio=settings.guard_min_ratio,
        small_list=settings.guard_small_list,
        allow_degraded=args.allow_degraded,
    )
    if reasons and not args.force:
        if args.dry_run:
            log.error("dry run: guard would reject this snapshot", extra={"reasons": reasons})
        else:
            write_rejected(output, candidate, reasons)
        return 2
    if reasons:
        log.warning("guard overridden by --force", extra={"reasons": reasons})
        candidate["warnings"].extend(f"guard overridden by --force: {r}" for r in reasons)

    if _content_unchanged(previous, candidate) and not args.force:
        log.info(
            "library content unchanged; keeping previous snapshot",
            extra={
                "content_hash": candidate["content_hash"],
                "snapshot_version": previous["snapshot_version"],
            },
        )
        return 0

    if args.dry_run:
        log.info(
            "dry run complete; nothing written",
            extra={"owned": len(candidate["owned"]), "waitlisted": len(candidate["waitlisted"])},
        )
        return 0

    write_snapshot(output, candidate)
    return 0


def main() -> None:
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        log.exception("unexpected failure")
        sys.exit(1)


if __name__ == "__main__":
    main()
