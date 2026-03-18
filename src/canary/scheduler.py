"""CANARY scheduler — entry point for running the pipeline."""

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

import yaml
from dotenv import load_dotenv

from canary.detection.store import DocumentStore
from canary.fetchers.base import BaseFetcher
from canary.fetchers.eurlex import EurLexFetcher
from canary.graph.graph import build_graph
from canary.graph.nodes import set_fetcher, set_store, set_vault_writer
from canary.graph.state import CANARYState
from canary.issues import IssueCollector
from canary.output.schema import generate_objective_note, generate_regulation_readme
from canary.output.vault import VaultWriter
from canary.tracing import RunMetrics, configure_langsmith

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = "config/sources.yaml"


def _resolve_config(args_config: str | None) -> Path:
    """Resolve config path from CLI arg, env var, or default."""
    path_str = args_config or os.environ.get("CANARY_CONFIG") or DEFAULT_CONFIG
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    return path


def _load_config(config_path: Path) -> dict:
    """Load and validate sources config from YAML."""
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {config_path}: {e}") from e

    if not config or "sources" not in config:
        raise ValueError(f"Config file {config_path} must contain a 'sources' key")
    return config


def _resolve_model(args_model: str | None) -> str:
    """Resolve model from CLI arg, env var, or default."""
    return args_model or os.environ.get("CANARY_MODEL") or "claude-sonnet-4-6"


def _get_fetcher(fetcher_type: str) -> BaseFetcher:
    """Factory for fetcher instances based on type string."""
    if fetcher_type == "eurlex":
        return EurLexFetcher()
    if fetcher_type == "ukleg":
        from canary.fetchers.ukleg import UKLegislationFetcher
        return UKLegislationFetcher()
    if fetcher_type == "nzleg":
        from canary.fetchers.nzleg import NZLegislationFetcher
        return NZLegislationFetcher()
    if fetcher_type == "irishstatute":
        from canary.fetchers.irishstatute import IrishStatuteFetcher
        return IrishStatuteFetcher()
    if fetcher_type == "govinfo":
        from canary.fetchers.govinfo import GovInfoFetcher
        return GovInfoFetcher()
    raise ValueError(f"Unknown fetcher type: {fetcher_type!r}. Available: eurlex, ukleg, nzleg, irishstatute, govinfo")


async def run_canary(
    vault_enabled: bool = False,
    source_filter: str | None = None,
    model: str = "claude-sonnet-4-6",
    config_path: Path | None = None,
) -> int:
    """Run the CANARY pipeline for all configured sources.

    Returns exit code: 0 = clean, 1 = warnings only, 2 = errors.
    """
    load_dotenv()

    run_id = f"run-{uuid.uuid4().hex[:12]}"
    issues = IssueCollector(run_id=run_id)

    # Configure LangSmith tracing
    tracing_enabled = configure_langsmith(run_id)

    # Initialize run metrics
    metrics = RunMetrics(run_id=run_id)
    metrics.start()

    logger.info(
        "CANARY run %s starting (vault=%s, tracing=%s, model=%s)",
        run_id, vault_enabled, tracing_enabled, model,
    )

    # Initialize components
    db_path = Path(os.environ.get("CANARY_DB_PATH", "data/canary.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    store = DocumentStore(db_path)

    # Load config
    if config_path is None:
        config_path = _resolve_config(None)
    config = _load_config(config_path)
    sources = config["sources"]

    # Filter sources if requested
    if source_filter:
        sources = [s for s in sources if s["id"] == source_filter]
        if not sources:
            logger.error("Source %r not found in config", source_filter)
            store.close()
            return 2

    # Group sources by fetcher type and create fetcher instances
    fetchers: dict[str, BaseFetcher] = {}
    vault_writer: VaultWriter | None = None

    set_store(store)

    if vault_enabled:
        try:
            vault_writer = VaultWriter()
            await vault_writer.connect()
            set_vault_writer(vault_writer)
            logger.info("Vault writer connected")
        except Exception as e:
            issues.error("vault", "connect", f"Vault connection failed: {e}")
            vault_writer = None
            set_vault_writer(None)

    graph = build_graph()

    logger.info("Processing %d source(s): %s", len(sources), ", ".join(s["id"] for s in sources))

    try:
        for idx, source in enumerate(sources, 1):
            logger.info(
                "=== [%d/%d] %s (%s) ===",
                idx, len(sources), source["label"], source["celex_id"],
            )

            # Select the right fetcher for this source
            fetcher_type = source.get("fetcher", "eurlex")
            if fetcher_type not in fetchers:
                fetchers[fetcher_type] = _get_fetcher(fetcher_type)
            fetcher = fetchers[fetcher_type]
            set_fetcher(fetcher)
            celex_id = source["celex_id"]

            # Track per-source metrics
            source_metrics = metrics.start_source(celex_id, source["label"])

            initial_state: CANARYState = {
                "current_source": source,
                "run_id": run_id,
                "model": model,
                "vault_enabled": vault_enabled,
                "errors": [],
            }

            try:
                result = await graph.ainvoke(initial_state)

                # Update source metrics from result
                if result.get("is_first_run"):
                    source_metrics.status = "baseline"
                elif result.get("changed"):
                    source_metrics.status = "changed"
                    extraction = result.get("extraction")
                    if extraction:
                        source_metrics.change_count = len(extraction.changes)
                    else:
                        issues.warning(
                            "extract", celex_id,
                            "Change detected but extraction returned no results",
                        )
                    verification = result.get("verification")
                    if verification:
                        source_metrics.citations_total = len(verification.results)
                        source_metrics.citations_verified = (
                            source_metrics.citations_total - verification.unverified_count
                        )
                        if verification.unverified_count > 0:
                            issues.warning(
                                "verify", celex_id,
                                f"{verification.unverified_count} unverified citations "
                                f"out of {len(verification.results)}",
                            )
                    # Track token usage
                    ext_metrics = result.get("extraction_metrics")
                    if ext_metrics:
                        metrics.extraction_tokens_in += ext_metrics.input_tokens
                        metrics.extraction_tokens_out += ext_metrics.output_tokens
                else:
                    source_metrics.status = "no_change"

                source_metrics.hash = result.get("new_hash")
                source_metrics.vault_path = result.get("vault_path")

                # Collect pipeline errors into issues
                errors = result.get("errors", [])
                if errors:
                    source_metrics.error = "; ".join(errors)
                    for err in errors:
                        issues.error("pipeline", celex_id, err)

                # Flag vault write failures
                if (
                    vault_enabled
                    and result.get("changed")
                    and result.get("report")
                    and result.get("vault_path") is None
                ):
                    issues.warning(
                        "vault", celex_id,
                        "Change report was not written to vault",
                    )

            except Exception as e:
                source_metrics.status = "error"
                source_metrics.error = str(e)
                issues.error("pipeline", celex_id, f"Pipeline crashed: {e}", detail=str(type(e)))

            metrics.finish_source(source_metrics)

    finally:
        for f in fetchers.values():
            await f.close()

        # Finalize and persist run metrics
        metrics.finish()
        store.save_run(metrics)

        # Print run summary (machine-readable JSON to stdout)
        summary = metrics.summary()
        logger.info(
            "=== Run complete: %d source(s), %d change(s), %d error(s), %.1fs ===",
            summary["sources_checked"], summary["changes_detected"],
            summary["errors"], summary.get("duration_ms", 0) / 1000,
        )
        print(json.dumps(summary, indent=2))

        # Write issues file
        issues_path = issues.write()
        if issues_path:
            logger.info("Issues written to %s", issues_path)

        store.close()
        if vault_writer:
            await vault_writer.disconnect()

    if issues.has_errors:
        return 2
    if issues.has_warnings:
        return 1
    return 0


async def run_extract_objectives(
    source_id: str | None = None,
    count: int | None = None,
    vault_enabled: bool = True,
    model: str = "claude-sonnet-4-6",
    config_path: Path | None = None,
) -> int:
    """Extract compliance objectives from a regulation and write to vault.

    Returns exit code: 0 = clean, 1 = warnings, 2 = errors.
    """
    from canary.analysis.normalize import citation_matches
    from canary.analysis.objectives import extract_objectives, requote_citations

    load_dotenv()

    run_id = f"obj-{uuid.uuid4().hex[:12]}"
    issues = IssueCollector(run_id=run_id)
    configure_langsmith(run_id)

    # Load sources
    if config_path is None:
        config_path = _resolve_config(None)
    config = _load_config(config_path)

    sources = config["sources"]
    if source_id:
        sources = [s for s in sources if s["id"] == source_id]
        if not sources:
            issues.error("config", source_id or "unknown", f"Source '{source_id}' not found")
            issues.write()
            return 2

    source = sources[0]
    celex_id = source["celex_id"]

    count_label = str(count) if count else "all"
    logger.info(
        "=== Extracting %s objectives from %s (%s) ===",
        count_label, source["label"], celex_id,
    )

    # Fetch the document
    fetcher_type = source.get("fetcher", "eurlex")
    logger.info("[fetch] Fetching %s via %s...", celex_id, fetcher_type)
    fetcher = _get_fetcher(fetcher_type)
    try:
        text, _ = await fetcher.fetch_text(celex_id)
    except Exception as e:
        issues.error("fetch", celex_id, f"Fetch failed: {e}")
        issues.write()
        await fetcher.close()
        return 2
    finally:
        await fetcher.close()

    if not text:
        issues.error("fetch", celex_id, "Fetch returned empty document")
        issues.write()
        return 2

    logger.info("[fetch] %s — %d chars fetched", celex_id, len(text))

    # Extract objectives via Claude
    logger.info("[extract] Extracting objectives via Claude...")
    try:
        extraction, obj_metrics = await extract_objectives(text, count=count, model=model)
    except Exception as e:
        issues.error("extract", celex_id, f"Objective extraction failed: {e}", detail=str(type(e)))
        issues.write()
        return 2

    chunks_info = f", {obj_metrics.chunks} chunks" if obj_metrics.chunks > 1 else ""
    logger.info(
        "[extract] %d objectives extracted (%s, %.1fs, %d/%d tokens%s)",
        len(extraction.objectives),
        obj_metrics.model,
        obj_metrics.duration_ms / 1000,
        obj_metrics.input_tokens,
        obj_metrics.output_tokens,
        chunks_info,
    )

    # Quality checks: only warn about count if explicitly requested and single-pass
    if count and obj_metrics.chunks == 1 and len(extraction.objectives) < count:
        issues.warning(
            "extract", celex_id,
            f"Requested {count} objectives but only got {len(extraction.objectives)}",
        )

    # Citation retry: re-quote any objectives that failed verification
    unverified_objs = [
        obj for obj in extraction.objectives
        if not citation_matches(obj.verbatim_quote, text)
    ]
    if unverified_objs:
        logger.info(
            "[verify] %d/%d citations unverified — attempting re-quote...",
            len(unverified_objs), len(extraction.objectives),
        )
        try:
            corrected, retry_metrics = await requote_citations(
                unverified_objs, text, model=model,
            )
            obj_metrics.input_tokens += retry_metrics.input_tokens
            obj_metrics.output_tokens += retry_metrics.output_tokens
            obj_metrics.duration_ms += retry_metrics.duration_ms

            # Build lookup: article → corrected objective
            corrected_by_article = {c.article: c for c in corrected}
            fixed = 0
            for i, obj in enumerate(extraction.objectives):
                if obj.article in corrected_by_article:
                    replacement = corrected_by_article[obj.article]
                    if citation_matches(replacement.verbatim_quote, text):
                        extraction.objectives[i] = replacement
                        fixed += 1
            logger.info(
                "Re-quote fixed %d/%d citations (%.0fms, %d/%d tokens)",
                fixed, len(unverified_objs), retry_metrics.duration_ms,
                retry_metrics.input_tokens, retry_metrics.output_tokens,
            )
        except Exception as e:
            logger.warning("Citation retry failed: %s", e)

    # Connect vault writer
    vault_writer: VaultWriter | None = None
    if vault_enabled:
        logger.info("[vault] Connecting to Flywheel MCP server...")
        try:
            vault_writer = VaultWriter()
            await vault_writer.connect()
            logger.info("[vault] Connected — writing %d objectives to vault", len(extraction.objectives))
        except Exception as e:
            issues.error("vault", "connect", f"Vault connection failed: {e}")
            vault_writer = None

    # Track citation stats
    verified_count = 0
    unverified_count = 0
    verified_articles: set[str] = set()

    # Generate and write each objective note
    for i, obj in enumerate(extraction.objectives, 1):
        note_md = generate_objective_note(
            objective=obj,
            regulation_name=extraction.regulation_name,
            celex_id=celex_id,
            run_id=run_id,
            source_text=text,
        )

        # Check citation verification from the generated note
        if "citation: verified" in note_md:
            verified_count += 1
            verified_articles.add(obj.article)
        else:
            unverified_count += 1
            issues.warning(
                "verify", celex_id,
                f"{obj.article} — citation not verified against source text",
                detail=obj.verbatim_quote[:200],
            )

        # Quality: flag low confidence or missing fields
        if obj.materiality == "low":
            issues.warning(
                "extract", celex_id,
                f"{obj.article} — low materiality objective may not be relevant",
            )

        citation_tag = "verified" if "citation: verified" in note_md else "UNVERIFIED"
        logger.info(
            "[objective %d/%d] %s — %s (type=%s, materiality=%s, citation=%s)",
            i, len(extraction.objectives), obj.article, obj.title,
            obj.obligation_type, obj.materiality, citation_tag,
        )

        if vault_writer:
            reg_short = source["id"].lower()
            path = await vault_writer.write_objective(note_md, obj.article, reg_short)
            if not path:
                issues.error(
                    "vault", celex_id,
                    f"Failed to write {obj.article} to vault",
                )

    # Write regulation README index
    if vault_writer:
        from canary.output.vault import _split_frontmatter
        reg_short = source["id"].lower()
        readme_md = generate_regulation_readme(
            regulation_name=extraction.regulation_name,
            celex_id=celex_id,
            objectives=extraction.objectives,
            verified_articles=verified_articles,
            run_id=run_id,
        )
        fm, body = _split_frontmatter(readme_md)
        try:
            await vault_writer._call_tool(
                "vault_create_note",
                {
                    "path": f"{vault_writer._output_root}/objectives/{reg_short}/README.md",
                    "content": body,
                    "frontmatter": fm,
                    "overwrite": True,
                    "suggestOutgoingLinks": True,
                },
            )
            logger.info("Wrote regulation index: %s/README.md", reg_short)
        except Exception as e:
            logger.warning("Failed to write regulation index: %s", e)

    # Summary
    total_citations = verified_count + unverified_count
    logger.info(
        "=== Complete: %d objectives, %d/%d citations verified ===",
        len(extraction.objectives), verified_count, total_citations,
    )

    summary = {
        "run_id": run_id,
        "source": source["label"],
        "celex_id": celex_id,
        "source_chars": len(text),
        "chunks": obj_metrics.chunks,
        "objectives": len(extraction.objectives),
        "citations_verified": verified_count,
        "citations_total": total_citations,
        "tokens_in": obj_metrics.input_tokens,
        "tokens_out": obj_metrics.output_tokens,
        "duration_s": round(obj_metrics.duration_ms / 1000, 1),
    }
    print(json.dumps(summary, indent=2))

    if vault_writer:
        await vault_writer.log_to_daily(
            f"CANARY extracted {len(extraction.objectives)} compliance objectives "
            f"from {source['label']} ({verified_count}/{verified_count + unverified_count} verified)"
        )
        await vault_writer.disconnect()

    # Write issues file
    issues_path = issues.write()
    if issues_path:
        logger.info("Issues written to %s", issues_path)

    if issues.has_errors:
        return 2
    if issues.has_warnings:
        return 1
    return 0


def run_status() -> int:
    """Show status of recent runs and any outstanding issues."""
    load_dotenv()

    db_path = Path(os.environ.get("CANARY_DB_PATH", "data/canary.db"))
    if not db_path.exists():
        print("No database found. Run `canary` first to initialize.")
        return 1

    store = DocumentStore(db_path)

    # Recent runs
    runs = store.get_run_log(5)
    if not runs:
        print("No runs recorded.")
        store.close()
        return 0

    print("=== Recent Runs ===\n")
    for run in runs:
        status_icon = "OK" if run["errors"] == 0 else "ERR"
        print(
            f"  [{status_icon}] {run['run_id']}  "
            f"{run['started_at'][:19]}  "
            f"sources={run['sources_checked']}  "
            f"changes={run['changes_detected']}  "
            f"errors={run['errors']}  "
            f"{run['duration_ms']:.0f}ms"
        )

    # Latest run detail
    latest = runs[0]
    checks = store.get_source_checks(latest["run_id"])
    if checks:
        print(f"\n=== Latest: {latest['run_id']} ===\n")
        for check in checks:
            status_icon = {"no_change": ".", "changed": "!", "baseline": "+", "error": "X"}.get(
                check["status"], "?"
            )
            line = f"  [{status_icon}] {check['celex_id']}  {check['label']}  — {check['status']}"
            if check["change_count"]:
                line += f"  ({check['change_count']} changes)"
            if check["citations_total"]:
                line += f"  [{check['citations_verified']}/{check['citations_total']} citations]"
            if check["error"]:
                line += f"  ERROR: {check['error']}"
            print(line)

    # Check for issue files
    issues_dir = Path("data/issues")
    if issues_dir.exists():
        issue_files = sorted(issues_dir.glob("*.json"), reverse=True)
        if issue_files:
            print(f"\n=== Issue Files ({len(issue_files)}) ===\n")
            for f in issue_files[:5]:
                data = json.loads(f.read_text())
                print(
                    f"  {f.name}  "
                    f"errors={data['errors']}  warnings={data['warnings']}  "
                    f"total={data['total']}"
                )

    store.close()
    return 0


def run_prune(days: int = 90) -> int:
    """Prune old run data from the database."""
    load_dotenv()

    db_path = Path(os.environ.get("CANARY_DB_PATH", "data/canary.db"))
    if not db_path.exists():
        print("No database found.")
        return 1

    store = DocumentStore(db_path)
    result = store.prune(days=days)
    print(json.dumps(result, indent=2))
    store.close()
    return 0


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="CANARY — ESG regulatory change monitor")
    subparsers = parser.add_subparsers(dest="command")

    # Global options for default command
    parser.add_argument(
        "--no-vault",
        action="store_true",
        help="Disable vault writes (console output only)",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Filter to a single source ID from sources.yaml",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Claude model to use (default: claude-sonnet-4-6, or CANARY_MODEL env var)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to sources.yaml config (default: config/sources.yaml, or CANARY_CONFIG env var)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Set log level to DEBUG",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Set log level to WARNING",
    )

    # extract-objectives subcommand
    obj_parser = subparsers.add_parser(
        "extract-objectives",
        help="Extract compliance objectives from a regulation",
    )
    obj_parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Source ID from sources.yaml (default: first source)",
    )
    obj_parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Max objectives to extract (default: all)",
    )
    obj_parser.add_argument(
        "--no-vault",
        action="store_true",
        help="Disable vault writes",
    )
    obj_parser.add_argument("--model", type=str, default=None)
    obj_parser.add_argument("--config", type=str, default=None)

    # status subcommand
    subparsers.add_parser(
        "status",
        help="Show recent run status and issues",
    )

    # prune subcommand
    prune_parser = subparsers.add_parser(
        "prune",
        help="Delete old run data from the database",
    )
    prune_parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Delete data older than N days (default: 90)",
    )

    args = parser.parse_args()

    # Configure logging level
    if getattr(args, "verbose", False):
        log_level = logging.DEBUG
    elif getattr(args, "quiet", False):
        log_level = logging.WARNING
    else:
        log_level = logging.INFO

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )

    model = _resolve_model(getattr(args, "model", None))

    try:
        config_path = _resolve_config(getattr(args, "config", None))
    except FileNotFoundError as e:
        logger.error("%s", e)
        sys.exit(2)

    if args.command == "extract-objectives":
        exit_code = asyncio.run(
            run_extract_objectives(
                source_id=args.source,
                count=args.count,
                vault_enabled=not args.no_vault,
                model=model,
                config_path=config_path,
            )
        )
    elif args.command == "status":
        exit_code = run_status()
    elif args.command == "prune":
        exit_code = run_prune(days=args.days)
    else:
        exit_code = asyncio.run(
            run_canary(
                vault_enabled=not args.no_vault,
                source_filter=getattr(args, "source", None),
                model=model,
                config_path=config_path,
            )
        )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
