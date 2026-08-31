#!/usr/bin/env python3
"""Patch the 0.5.1 bridge executor to call the legacy netqueue parser safely."""
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding='utf-8')
old = """    command = list(ACTIONS[action])
    if action == 'lghs-update' and payload.get('target_commit'):
        command += ['--commit', normalize_target_commit(payload['target_commit'])]
    if command_id:
        # The controller command ID is the local side-effect idempotency key.
        command += ['--idempotency-key', command_id]
    return command
"""
new = """    command = list(ACTIONS[action])
    if command_id:
        # The controller command ID is the local side-effect idempotency key.
        command += ['--idempotency-key', command_id]
    if action == 'lghs-update' and payload.get('target_commit'):
        # 0.5.1 netqueue uses a catch-all positional parser. Put its real
        # option first, then terminate option parsing so --commit reaches
        # the legacy positional argument list instead of argparse rejecting it.
        command += ['--', '--commit', normalize_target_commit(payload['target_commit'])]
    return command
"""
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit('executor compatibility patch target not found')
path.write_text(text, encoding='utf-8')
