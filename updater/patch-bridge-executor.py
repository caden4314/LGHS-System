#!/usr/bin/env python3
"""Patch the 0.5.1 bridge executor to speak the legacy netqueue CLI exactly.

The legacy netqueue parser accepts the target commit as positional remainder
arguments after `--`, while `--idempotency-key` remains a real enqueue option.
The v0.6 executor uses a native `--commit` option and must not use this patch.
"""
from pathlib import Path
import sys

OLD = """    command = list(ACTIONS[action])\n    if action == 'lghs-update' and payload.get('target_commit'):\n        command += ['--commit', normalize_target_commit(payload['target_commit'])]\n    if command_id:\n        # The controller command ID is the local side-effect idempotency key.\n        command += ['--idempotency-key', command_id]\n    return command\n"""

NEW = """    command = list(ACTIONS[action])\n    if command_id:\n        # The controller command ID is the local side-effect idempotency key.\n        command += ['--idempotency-key', command_id]\n    if action == 'lghs-update' and payload.get('target_commit'):\n        # 0.5.1 netqueue exposes commit as positional remainder args, not a\n        # native argparse option. `--` preserves the literal --commit token.\n        command += ['--', '--commit', normalize_target_commit(payload['target_commit'])]\n    return command\n"""


def patch(path: Path) -> None:
    text = path.read_text(encoding='utf-8')
    if NEW in text:
        print(f'bridge executor compatibility already present: {path}')
        return
    if OLD not in text:
        raise SystemExit(f'expected executor command block not found: {path}')
    path.write_text(text.replace(OLD, NEW, 1), encoding='utf-8')
    print(f'bridge executor compatibility installed: {path}')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: patch-bridge-executor.py PATH')
    patch(Path(sys.argv[1]))
