#!/usr/bin/env python3
"""Patch an installed LGHS agent to verify root filesystem writability by probe.

Some Linux/statvfs combinations can report ST_RDONLY unexpectedly. The managed
agent runs unprivileged, so use a writable state-directory probe on the same
root filesystem as the LGHS state rather than treating the flag alone as
fatal. This patch is intentionally narrow and idempotent for hardware RC use.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "LGHS_ROOT_WRITABLE_PROBE_FIX"
OLD = "    root_readonly = bool(stat.f_flag & getattr(os, 'ST_RDONLY', 1))\n"
NEW = """    # LGHS_ROOT_WRITABLE_PROBE_FIX: validate writability instead of trusting\n    # ST_RDONLY alone. The agent owns STATE_ROOT, which lives on the managed\n    # root filesystem on LGHS images. A successful create/unlink proves the\n    # filesystem backing managed state is actually writable.\n    root_readonly = bool(stat.f_flag & getattr(os, 'ST_RDONLY', 1))\n    probe = STATE_ROOT / '.root-writable-probe'\n    try:\n        probe.write_text('ok\\n', encoding='utf-8')\n        probe.unlink(missing_ok=True)\n        root_readonly = False\n    except OSError:\n        root_readonly = True\n"""


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else '/usr/local/sbin/lghs-agent')
    text = path.read_text(encoding='utf-8')
    if MARKER in text:
        print(f'root-writable health probe already installed: {path}')
        return 0
    if OLD not in text:
        raise SystemExit(f'legacy root-readonly probe not found in {path}')
    path.write_text(text.replace(OLD, NEW, 1), encoding='utf-8')
    print(f'root-writable health probe installed: {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
