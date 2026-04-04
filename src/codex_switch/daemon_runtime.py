from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import signal
import threading

from codex_switch.automation_db import AutomationStore
from codex_switch.paths import resolve_paths


class DaemonRuntime:
    def __init__(self, store: AutomationStore, poll_interval_seconds: float) -> None:
        self._store = store
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def run_forever(self) -> None:
        self._store.initialize()
        while not self._stop_event.wait(self._poll_interval_seconds):
            # v1 loop scaffold: telemetry ingestion/handoff orchestration is wired in later tasks.
            continue


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-switchd")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--home", default=None)
    run_parser.add_argument("--poll-interval", type=float, default=30.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command != "run":
        parser.error(f"unknown command: {args.command}")

    home = Path(args.home) if args.home is not None else None
    paths = resolve_paths(home=home)
    runtime = DaemonRuntime(
        store=AutomationStore(paths.automation_db_file),
        poll_interval_seconds=args.poll_interval,
    )

    def _handle_signal(_signum: int, _frame) -> None:
        runtime.request_stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    runtime.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
