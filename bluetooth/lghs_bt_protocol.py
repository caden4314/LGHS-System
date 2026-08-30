#!/usr/bin/env python3
"""LGHS Bluetooth bootstrap protocol primitives.

The Bluetooth link is treated as untrusted. Device-specific Fleet API tokens
provide mutual authentication while ephemeral X25519 keys provide forward
secrecy. Wi-Fi credentials are carried only inside AES-GCM ciphertext.
"""
import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PROTOCOL_VERSION = 1
MAX_FRAME = 16384
INFO = b"LGHS-BT-PROVISION-v1"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64(value: str) -> bytes:
    raw = value.encode("ascii")
    return base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def new_ephemeral():
    private = X25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return private, b64(public)


def transcript(controller_id, device_id, server_nonce, client_nonce, server_pub, client_pub):
    return {
        "v": PROTOCOL_VERSION,
        "controller_id": controller_id,
        "device_id": device_id,
        "server_nonce": server_nonce,
        "client_nonce": client_nonce,
        "server_pub": server_pub,
        "client_pub": client_pub,
    }


def proof(token: bytes, role: str, tx: dict) -> str:
    label = ("LGHS-BT-" + role.upper() + "-v1").encode("ascii")
    return b64(hmac.new(token, label + b"\0" + canonical(tx), hashlib.sha256).digest())


def verify_proof(token: bytes, role: str, tx: dict, supplied: str) -> bool:
    try:
        expected = unb64(proof(token, role, tx))
        actual = unb64(supplied)
    except Exception:
        return False
    return hmac.compare_digest(expected, actual)


def derive_key(private: X25519PrivateKey, peer_public_b64: str, token: bytes, tx: dict) -> bytes:
    peer = X25519PublicKey.from_public_bytes(unb64(peer_public_b64))
    shared = private.exchange(peer)
    salt = hmac.new(token, b"LGHS-BT-KDF-v1\0" + canonical(tx), hashlib.sha256).digest()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=INFO).derive(shared)


def encrypt_payload(key: bytes, tx: dict, payload: dict) -> dict:
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, canonical(payload), canonical(tx))
    return {"nonce": b64(nonce), "ciphertext": b64(ciphertext)}


def decrypt_payload(key: bytes, tx: dict, envelope: dict) -> dict:
    plaintext = AESGCM(key).decrypt(
        unb64(envelope["nonce"]),
        unb64(envelope["ciphertext"]),
        canonical(tx),
    )
    value = json.loads(plaintext)
    if not isinstance(value, dict):
        raise ValueError("invalid encrypted payload")
    return value


def send_frame(sock, obj: dict):
    data = canonical(obj) + b"\n"
    if len(data) > MAX_FRAME:
        raise ValueError("Bluetooth frame too large")
    sock.sendall(data)


def recv_frame(sock) -> dict:
    data = bytearray()
    while len(data) <= MAX_FRAME:
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("Bluetooth peer disconnected")
        if chunk == b"\n":
            break
        data.extend(chunk)
    if len(data) > MAX_FRAME:
        raise ValueError("Bluetooth frame too large")
    value = json.loads(bytes(data))
    if not isinstance(value, dict):
        raise ValueError("Bluetooth frame is not an object")
    return value
