from __future__ import annotations

import threading
import time

from codex_switch.daemon_runtime import DaemonRuntime, build_parser


class StoreSpy:
    def __init__(self) -> None:
        self.initialize_calls = 0

    def initialize(self) -> None:
        self.initialize_calls += 1


def test_daemon_runtime_parser_supports_run_command():
    parser = build_parser()

    namespace = parser.parse_args(["run", "--home", "/tmp/demo", "--poll-interval", "5"])

    assert namespace.command == "run"
    assert namespace.home == "/tmp/demo"
    assert namespace.poll_interval == 5.0


def test_daemon_runtime_run_forever_initializes_store_and_stops_on_request():
    store = StoreSpy()
    runtime = DaemonRuntime(store=store, poll_interval_seconds=0.01)
    thread = threading.Thread(target=runtime.run_forever)
    thread.start()
    time.sleep(0.03)

    runtime.request_stop()
    thread.join(timeout=1.0)

    assert store.initialize_calls == 1
    assert thread.is_alive() is False
