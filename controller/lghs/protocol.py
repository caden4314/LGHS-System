"""LGHS Fleet protocol v1 primitives.

The protocol layer deliberately has no transport or database dependencies. It
normalizes device identity, validates telemetry envelopes, and defines command
state ordering shared by API/controller code.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Mapping

PROTOCOL_VERSION = 1
DEVICE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,63}$")

COMMAND_STATES = (
    "queued",
    "delivered",
    "received",
    "accepted",
    "running",
    "succeeded",
    "failed",
    "timed_out",
    "rejected",
    "canceled",
)
TERMINAL_COMMAND_STATES = frozenset({"succeeded", "failed", "timed_out", "rejected", "canceled"})
COMMAND_ORDER = {
    "queued": 0,
    "delivered": 1,
    "received": 2,
    "accepted": 3,
    "running": 4,
    "succeeded": 5,
    "failed": 5,
    "timed_out": 5,
    "rejected": 5,
    "canceled": 5,
}
ALLOWED_COMMANDS = frozenset({"lghs-update", "os-update", "reboot"})


class ProtocolError(ValueError):
    pass


def normalize_device_id(value: Any) -> str:
    device = str(value or "").strip().upper()
    if not DEVICE_RE.fullmatch(device):
        raise ProtocolError("invalid device_id")
    return device


def normalize_command_state(value: Any) -> str:
    state = str(value or "queued").strip().lower()
    # 0.4 compatibility during staged migration.
    if state == "pending":
        state = "queued"
    elif state in {"complete", "reboot_required"}:
        state = "succeeded"
    if state not in COMMAND_ORDER:
        raise ProtocolError(f"invalid command state: {state}")
    return state


def state_can_advance(old: Any, new: Any) -> bool:
    old_state = normalize_command_state(old)
    new_state = normalize_command_state(new)
    if old_state in TERMINAL_COMMAND_STATES:
        return old_state == new_state
    return COMMAND_ORDER[new_state] >= COMMAND_ORDER[old_state]


@dataclass(frozen=True)
class TelemetryEnvelope:
    protocol: int
    agent_version: str
    device_id: str
    boot_id: str
    sequence: int
    sent_at: float
    payload: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, now: float | None = None) -> "TelemetryEnvelope":
        if not isinstance(raw, Mapping):
            raise ProtocolError("telemetry envelope must be an object")
        protocol = int(raw.get("protocol", 0) or 0)
        if protocol != PROTOCOL_VERSION:
            raise ProtocolError(f"unsupported protocol: {protocol}")
        device_id = normalize_device_id(raw.get("device_id"))
        agent_version = str(raw.get("agent_version") or "").strip()
        if not agent_version:
            raise ProtocolError("missing agent_version")
        boot_id = str(raw.get("boot_id") or "").strip()
        if not boot_id or len(boot_id) > 128:
            raise ProtocolError("invalid boot_id")
        try:
            sequence = int(raw.get("sequence"))
        except (TypeError, ValueError):
            raise ProtocolError("invalid sequence") from None
        if sequence < 0:
            raise ProtocolError("invalid sequence")
        try:
            sent_at = float(raw.get("sent_at"))
        except (TypeError, ValueError):
            raise ProtocolError("invalid sent_at") from None
        current = time.time() if now is None else float(now)
        # Keep this wide enough for bad school-network clocks while still
        # rejecting obviously nonsensical/replayed timestamps.
        if sent_at <= 0 or abs(current - sent_at) > 7 * 24 * 60 * 60:
            raise ProtocolError("sent_at outside allowed window")
        payload = raw.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ProtocolError("payload must be an object")
        return cls(protocol, agent_version, device_id, boot_id, sequence, sent_at, payload)


def response(commands: list[dict[str, Any]], *, received_at: float | None = None) -> dict[str, Any]:
    return {
        "protocol": PROTOCOL_VERSION,
        "received_at": time.time() if received_at is None else float(received_at),
        "commands": commands,
    }
