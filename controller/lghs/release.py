"""Signed LGHS release manifest primitives for the controller."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_FILE = Path('/etc/lghs/secrets/release-signing-key')
STATE_ROOT = Path('/var/lib/lghs/release')
SEQUENCE_FILE = STATE_ROOT / 'release-sequence'
CURRENT_FILE = STATE_ROOT / 'current.json'
LOCK_FILE = STATE_ROOT / 'lock'
VERSION_FILE = Path('/etc/lghs/version')
UPDATE_ENV = Path('/etc/lghs/update.env')
MANIFEST_FIELDS = frozenset({'schema','release_sequence','channel','version','commit','created_at','expires_at','minimum_updater'})


def _atomic(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700 if 'secrets' in path.parts else 0o750)
    tmp = path.with_name('.' + path.name + '.tmp')
    with tmp.open('wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def canonical_manifest(value: dict[str, Any]) -> bytes:
    if set(value) != MANIFEST_FIELDS:
        raise ValueError('release manifest has unexpected fields')
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')


def validate_public_key_b64(value: Any) -> bytes:
    text = str(value or '').strip()
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception as exc:
        raise ValueError('invalid Ed25519 public key encoding') from exc
    if len(raw) != 32:
        raise ValueError('Ed25519 public key must be exactly 32 bytes')
    return raw


def validate_release_artifact(manifest_b64: Any, signature_b64: Any) -> tuple[bytes, bytes]:
    try:
        manifest_raw = base64.b64decode(str(manifest_b64 or '').strip(), validate=True)
        signature = base64.b64decode(str(signature_b64 or '').strip(), validate=True)
    except Exception as exc:
        raise ValueError('invalid signed release base64') from exc
    if not manifest_raw or len(manifest_raw) > 4096:
        raise ValueError('release manifest has invalid size')
    if len(signature) != 64:
        raise ValueError('Ed25519 release signature must be exactly 64 bytes')
    try:
        manifest = json.loads(manifest_raw.decode('utf-8'))
    except Exception as exc:
        raise ValueError('release manifest is not valid JSON') from exc
    if not isinstance(manifest, dict) or canonical_manifest(manifest) != manifest_raw:
        raise ValueError('release manifest is not canonical')
    return manifest_raw, signature


@contextmanager
def release_lock() -> Iterator[None]:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    handle = LOCK_FILE.open('a+b')
    try:
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except ImportError:
            pass
        handle.close()


def generate_key() -> str:
    if KEY_FILE.exists():
        return public_key_b64()
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    _atomic(KEY_FILE, pem, 0o600)
    return public_key_b64()


def load_private() -> Ed25519PrivateKey:
    raw = KEY_FILE.read_bytes()
    key = serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('release signing key is not Ed25519')
    return key


def public_key_b64() -> str:
    key = load_private().public_key()
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode('ascii')


def public_fingerprint() -> str:
    return hashlib.sha256(validate_public_key_b64(public_key_b64())).hexdigest()


def controller_channel() -> str:
    try:
        for line in UPDATE_ENV.read_text(encoding='utf-8').splitlines():
            if line.startswith('LGHS_UPDATE_BRANCH='):
                value = line.split('=', 1)[1].strip()
                if value:
                    return value
    except Exception:
        pass
    return 'main'


def controller_version() -> str:
    try:
        value = VERSION_FILE.read_text(encoding='utf-8').strip()
        if value:
            return value
    except Exception:
        pass
    return '0.6.0'


def _load_current() -> dict[str, Any]:
    try:
        value = json.loads(CURRENT_FILE.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _read_sequence() -> int:
    try:
        return max(0, int(SEQUENCE_FILE.read_text(encoding='utf-8').strip()))
    except Exception:
        return 0


def issue_release(commit: str, *, channel: str | None = None, version: str | None = None, minimum_updater: str = '0.6.0', ttl_seconds: int = 7 * 86400, now: float | None = None, force_new: bool = False) -> dict[str, Any]:
    commit = str(commit or '').strip().lower()
    if len(commit) != 40 or any(ch not in '0123456789abcdef' for ch in commit):
        raise ValueError('release commit must be an exact 40-character Git SHA')
    channel = str(channel or controller_channel()).strip()
    version = str(version or controller_version()).strip()
    if not channel or not version or not minimum_updater:
        raise ValueError('release channel/version/minimum_updater are required')
    ttl = max(3600, min(int(ttl_seconds), 30 * 86400))
    ts = int(time.time() if now is None else now)
    with release_lock():
        current = _load_current()
        manifest = current.get('manifest') if isinstance(current.get('manifest'), dict) else {}
        reusable = (
            not force_new and manifest.get('commit') == commit and manifest.get('channel') == channel and
            manifest.get('version') == version and manifest.get('minimum_updater') == minimum_updater and
            int(manifest.get('expires_at') or 0) > ts + 3600 and
            current.get('manifest_b64') and current.get('signature_b64')
        )
        if reusable:
            return current
        sequence = _read_sequence() + 1
        manifest = {
            'schema': 1,
            'release_sequence': sequence,
            'channel': channel,
            'version': version,
            'commit': commit,
            'created_at': ts,
            'expires_at': ts + ttl,
            'minimum_updater': minimum_updater,
        }
        canonical = canonical_manifest(manifest)
        signature = load_private().sign(canonical)
        bundle = {
            'manifest': manifest,
            'manifest_b64': base64.b64encode(canonical).decode('ascii'),
            'signature_b64': base64.b64encode(signature).decode('ascii'),
            'public_key_fingerprint_sha256': public_fingerprint(),
        }
        _atomic(SEQUENCE_FILE, (str(sequence) + '\n').encode(), 0o640)
        _atomic(CURRENT_FILE, (json.dumps(bundle, sort_keys=True, separators=(',', ':')) + '\n').encode(), 0o640)
        return bundle


def augment_update_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload or {})
    if not out.get('target_commit') or not KEY_FILE.exists():
        return out
    manifest = out.get('release_manifest_b64')
    signature = out.get('release_signature_b64')
    if bool(manifest) != bool(signature):
        raise ValueError('release manifest and signature must be supplied together')
    if manifest and signature:
        return out
    bundle = issue_release(str(out['target_commit']), channel=str(out.get('target_channel') or controller_channel()))
    out['release_manifest_b64'] = bundle['manifest_b64']
    out['release_signature_b64'] = bundle['signature_b64']
    return out
