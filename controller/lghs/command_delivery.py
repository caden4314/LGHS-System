"""Prepare Fleet HTTPS command payloads immediately before delivery.

Offline students may reconnect long after a rollout was scheduled. Signing at
dispatch time would embed an expired seven-day manifest in a still-live command.
Only the controller is authorized to create an Ed25519 signature; the Pi still
verifies that signature, the exact Git commit and the release sequence.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import release

_UPDATE_FIELDS = frozenset({
    "target_commit", "target_channel", "release_manifest_b64",
    "release_signature_b64",
})
# Older controller builds accidentally included these DB-only fields.
_LEGACY_DB_FIELDS = frozenset({"deployment_id", "phase"})


def prepare_delivery(commands: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared = []
    for source in commands:
        item = dict(source)
        if str(item.get("action") or "") != "lghs-update":
            prepared.append(item)
            continue

        payload = item.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("invalid update payload")
        unexpected = set(payload) - _UPDATE_FIELDS - _LEGACY_DB_FIELDS
        if unexpected:
            raise ValueError("unexpected fields in update command")
        payload = {key: value for key, value in payload.items() if key in _UPDATE_FIELDS}
        commit = payload.get("target_commit")
        if commit:
            if release.KEY_FILE.is_file():
                # Re-sign at delivery, even if a stale artifact was stored when
                # the command was originally queued. issue_release() serializes
                # signing and reuses an unexpired bundle for the same target.
                payload.pop("release_manifest_b64", None)
                payload.pop("release_signature_b64", None)
                payload = release.augment_update_payload(payload)
            else:
                raise RuntimeError("release signing key unavailable for pinned update")
        item["payload"] = payload
        prepared.append(item)
    return prepared
