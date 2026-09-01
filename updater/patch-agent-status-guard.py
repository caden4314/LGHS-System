#!/usr/bin/env python3
"""Patch the installed/source LGHS agent so stale updater status cannot finish a new command.

A command must first be accepted by the privileged executor. The updater status
used to advance it must also belong to an updater run that started at or after
that acceptance. This prevents an old `complete` status file from racing a
newly received fleet command and marking it succeeded before local execution.
"""
from pathlib import Path
import sys

OLD = """        started = float(status.get('started_at') or 0)\n        accepted = float(row.get('accepted_at') or 0)\n        if not started or started + 1 < accepted:\n            continue\n"""
NEW = """        started = float(status.get('started_at') or 0)\n        accepted = float(row.get('accepted_at') or 0)\n        # Never attach updater state to a merely received command. A local\n        # executor acceptance timestamp is the causal boundary for this work.\n        if not accepted:\n            continue\n        # Ignore status from an updater invocation that predates this command.\n        # The one-second tolerance only covers timestamp/report scheduling skew.\n        if not started or started + 1 < accepted:\n            continue\n"""


def patch(path: Path) -> None:
    text = path.read_text(encoding='utf-8')
    if NEW in text:
        print(f'agent status guard already present: {path}')
        return
    if OLD not in text:
        raise SystemExit(f'expected agent progress block not found: {path}')
    path.write_text(text.replace(OLD, NEW, 1), encoding='utf-8')
    print(f'agent status guard installed: {path}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('usage: patch-agent-status-guard.py PATH [PATH ...]')
    for raw in sys.argv[1:]:
        patch(Path(raw))
