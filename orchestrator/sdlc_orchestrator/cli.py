from __future__ import annotations

import argparse
import json
import sys

from . import db
from .assignment import assignment_key, matches_role
from .config import Config, ConfigError
from .hermes_client import HermesClient, extract_run_id
from .locking import LockNotAcquired, nonblocking_lock
from .prompts import build_prompt, session_id
from .provider_base import WorkItem
from . import provider_github, provider_gitlab, reconciler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sdlc_orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run-once")
    subparsers.add_parser("reconcile")
    subparsers.add_parser("status")
    requeue_parser = subparsers.add_parser("requeue")
    requeue_parser.add_argument("--assignment-key")
    requeue_parser.add_argument("--status", action="append", dest="statuses")
    requeue_parser.add_argument("--limit", type=int)
    requeue_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        config = Config.from_env()
        if args.command == "run-once":
            return _print(run_once(config))
        if args.command == "reconcile":
            return _print(reconcile_only(config))
        if args.command == "status":
            return _print(status(config))
        if args.command == "requeue":
            return _print(requeue(config, assignment_key=args.assignment_key, statuses=args.statuses, limit=args.limit, dry_run=args.dry_run))
    except ConfigError as exc:
        return _print({"status": "ERROR", "error": str(exc)}, exit_code=2)
    except Exception as exc:
        return _print({"status": "ERROR", "error": str(exc)}, exit_code=1)
    return 1


def run_once(config: Config) -> dict:
    if not config.enabled:
        return {"status": "NO_OP", "reason": "orchestrator disabled", "role": config.role}
    try:
        with nonblocking_lock(config.lock_path):
            with db.connect(config.db_path) as conn:
                db.init_db(conn)
                client = HermesClient(config)
                reconciliation = reconciler.reconcile(conn, client, config, _transition_adapter(config))
                items = _fetch_items(config)
                matched = 0
                created = 0
                for item in items:
                    if not matches_role(item, config):
                        continue
                    matched += 1
                    work_item_id = db.upsert_work_item(conn, item)
                    key = assignment_key(item, config.role)
                    if db.ensure_assignment(conn, key, work_item_id, config.role):
                        created += 1
                started = _start_pending(conn, config, client)
                return {
                    "status": "OK",
                    "role": config.role,
                    "provider": config.provider,
                    "fetched": len(items),
                    "matched": matched,
                    "created_assignments": created,
                    "started_runs": started,
                    "reconciliation": reconciliation,
                }
    except LockNotAcquired:
        return {"status": "NO_OP", "reason": "lock held", "role": config.role}


def reconcile_only(config: Config) -> dict:
    with db.connect(config.db_path) as conn:
        db.init_db(conn)
        return {"status": "OK", "reconciliation": reconciler.reconcile(conn, HermesClient(config), config, _transition_adapter(config))}


def status(config: Config) -> dict:
    with db.connect(config.db_path) as conn:
        db.init_db(conn)
        return {
            "status": "OK",
            "role": config.role,
            "enabled": config.enabled,
            "apply_transitions": config.apply_transitions,
            "transition_comment_only": config.transition_comment_only,
            "counts": db.counts(conn),
            "assignment_statuses": db.assignment_status_counts(conn, config.role),
            "run_statuses": db.run_status_counts(conn, config.role),
            "queue": db.queue_counts(conn, config.role),
        }


def requeue(
    config: Config,
    *,
    assignment_key: str | None = None,
    statuses: list[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    safe_statuses = {"BLOCKED_CONFIG", "FAILED_FINAL", "LOST", "FAILED"}
    selected_statuses = {status.strip().upper() for status in statuses} if statuses else safe_statuses
    with db.connect(config.db_path) as conn:
        db.init_db(conn)
        matches = db.matching_requeue_assignments(
            conn,
            role=config.role,
            statuses=selected_statuses,
            assignment_key=assignment_key,
            limit=limit,
        )
        if dry_run:
            return {
                "status": "OK",
                "matched": len(matches),
                "requeued": 0,
                "dry_run": True,
                "assignments": [dict(row) for row in matches],
            }
        requeued = db.requeue_assignments(
            conn,
            role=config.role,
            statuses=selected_statuses,
            assignment_key=assignment_key,
            limit=limit,
        )
        return {"status": "OK", "matched": len(matches), "requeued": requeued, "dry_run": False}


def _fetch_items(config: Config) -> list[WorkItem]:
    if config.provider == "github":
        return provider_github.fetch_issues(config)
    if config.provider == "gitlab":
        return provider_gitlab.fetch_issues(config)
    return []


def _transition_adapter(config: Config):
    if not config.apply_transitions:
        return None
    if config.provider == "github":
        return provider_github.GitHubTransitionAdapter(config)
    if config.provider == "gitlab":
        return provider_gitlab.GitLabTransitionAdapter(config)
    return None


def _start_pending(conn, config: Config, client: HermesClient) -> int:
    started = 0
    for row in db.pending_assignments(conn, config.role, config.max_starts_per_tick):
        item = db.row_to_work_item(row)
        key = row["assignment_key"]
        sid = session_id(item, config.role)
        prompt = build_prompt(item, config.role, key)
        response = client.submit_run(
            model=f"hermes-{config.role}",
            session_id=sid,
            prompt=prompt,
            idempotency_key=key,
        )
        db.mark_assignment_started(conn, key, extract_run_id(response), sid)
        started += 1
    return started


def _print(payload: dict, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
