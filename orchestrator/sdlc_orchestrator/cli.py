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
    args = parser.parse_args(argv)

    try:
        config = Config.from_env()
        if args.command == "run-once":
            return _print(run_once(config))
        if args.command == "reconcile":
            return _print(reconcile_only(config))
        if args.command == "status":
            return _print(status(config))
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
                reconciliation = reconciler.reconcile(conn, client)
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
        return {"status": "OK", "reconciliation": reconciler.reconcile(conn, HermesClient(config))}


def status(config: Config) -> dict:
    with db.connect(config.db_path) as conn:
        db.init_db(conn)
        return {"status": "OK", "role": config.role, "enabled": config.enabled, "counts": db.counts(conn)}


def _fetch_items(config: Config) -> list[WorkItem]:
    if config.provider == "github":
        return provider_github.fetch_issues(config)
    if config.provider == "gitlab":
        return provider_gitlab.fetch_issues(config)
    return []


def _start_pending(conn, config: Config, client: HermesClient) -> int:
    started = 0
    for row in db.pending_assignments(conn, config.max_starts_per_tick):
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
