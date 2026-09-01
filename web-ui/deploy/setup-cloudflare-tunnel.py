#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pwd
import grp
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.cloudflare.com/client/v4"
TOKEN_FILE = Path("/etc/lghs/secrets/cloudflare-api-token")
CONF_FILE = Path("/etc/lghs/cloudflare.conf")
WEB_ENV = Path("/etc/lghs/fleet-web.env")
ROLE_FILE = Path("/etc/lghs/web-roles.json")
CF_DIR = Path("/etc/cloudflared")
CONNECTOR_TOKEN = CF_DIR / "lghs-fleet-ui.token"
SERVICE_FILE = Path("/etc/systemd/system/lghs-fleet-web-cloudflared.service")
SERVICE_USER = "lghs-cloudflare-ui"
TUNNEL_NAME = "LGHS-FLEET-UI"
DEFAULT_HOST = "fleet.scenicrouteservers.com"


def load_conf() -> dict[str, str]:
    out: dict[str, str] = {}
    if CONF_FILE.exists():
        for raw in CONF_FILE.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            out[key.strip()] = value.strip()
    return out


def api(token: str, method: str, path: str, body=None):
    data = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            payload = json.load(exc)
        except Exception:
            payload = {"success": False, "errors": [{"message": f"HTTP {exc.code}"}]}
    if not payload.get("success"):
        raise RuntimeError(f"Cloudflare API {method} {path} failed: {payload.get('errors')}")
    return payload.get("result")


def ensure_user() -> tuple[int, int]:
    try:
        account = pwd.getpwnam(SERVICE_USER)
    except KeyError:
        subprocess.run(
            ["useradd", "--system", "--no-create-home", "--home-dir", "/nonexistent", "--shell", "/usr/sbin/nologin", SERVICE_USER],
            check=True,
        )
        account = pwd.getpwnam(SERVICE_USER)
    return account.pw_uid, grp.getgrnam(SERVICE_USER).gr_gid


def atomic_secret(path: Path, value: str, uid: int, gid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value.strip() + "\n")
        os.chmod(name, 0o440)
        os.chown(name, uid, gid)
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def access_configured() -> bool:
    try:
        text = WEB_ENV.read_text(encoding="utf-8")
        roles = json.loads(ROLE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False
    users = roles.get("users", {}) if isinstance(roles, dict) else {}
    return "CHANGE-ME" not in text and bool(users)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the dedicated LGHS Fleet Web Cloudflare Tunnel")
    parser.add_argument("--hostname", default=DEFAULT_HOST)
    parser.add_argument("--start", action="store_true", help="start the connector after setup; requires configured Access identity/roles")
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise SystemExit("Run with sudo")
    if not TOKEN_FILE.exists() or not TOKEN_FILE.read_text(encoding="utf-8").strip():
        raise RuntimeError(f"missing {TOKEN_FILE}")

    conf = load_conf()
    account_id = conf.get("ACCOUNT_ID", "").strip()
    zone = conf.get("ZONE", "scenicrouteservers.com").strip()
    if not account_id:
        raise RuntimeError(f"ACCOUNT_ID is not set in {CONF_FILE}")

    hostname = args.hostname.strip().lower()
    if not hostname.endswith("." + zone) and hostname != zone:
        raise RuntimeError(f"hostname {hostname} is outside configured zone {zone}")

    cloudflared = shutil.which("cloudflared") or "/usr/local/bin/cloudflared"
    if not os.path.exists(cloudflared):
        raise RuntimeError("cloudflared is not installed on LGCSCONT")

    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    zones = api(token, "GET", "/zones?" + urllib.parse.urlencode({"name": zone}))
    if not zones:
        raise RuntimeError(f"zone not found or token lacks zone read access: {zone}")
    zone_id = zones[0]["id"]

    tunnels = api(token, "GET", f"/accounts/{account_id}/cfd_tunnel?is_deleted=false")
    tunnel = next((item for item in tunnels if item.get("name") == TUNNEL_NAME), None)
    if tunnel is None:
        tunnel = api(token, "POST", f"/accounts/{account_id}/cfd_tunnel", {"name": TUNNEL_NAME, "config_src": "cloudflare"})
    tunnel_id = tunnel["id"]

    api(token, "PUT", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations", {
        "config": {
            "ingress": [
                {"hostname": hostname, "service": "http://127.0.0.1:8790"},
                {"service": "http_status:404"},
            ]
        }
    })

    existing = api(token, "GET", f"/zones/{zone_id}/dns_records?" + urllib.parse.urlencode({"type": "CNAME", "name": hostname}))
    record = {"type": "CNAME", "name": hostname, "content": f"{tunnel_id}.cfargotunnel.com", "proxied": True}
    if existing:
        api(token, "PUT", f"/zones/{zone_id}/dns_records/{existing[0]['id']}", record)
    else:
        api(token, "POST", f"/zones/{zone_id}/dns_records", record)

    connector_token = api(token, "GET", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token")
    uid, gid = ensure_user()
    atomic_secret(CONNECTOR_TOKEN, str(connector_token), uid, gid)
    del connector_token

    service = f"""[Unit]\nDescription=LGHS Fleet Web Cloudflare Tunnel\nAfter=network-online.target lghs-fleet-web.service\nWants=network-online.target\nRequires=lghs-fleet-web.service\n\n[Service]\nType=simple\nUser={SERVICE_USER}\nGroup={SERVICE_USER}\nExecStart={cloudflared} tunnel --no-autoupdate run --token-file {CONNECTOR_TOKEN}\nRestart=on-failure\nRestartSec=5\nNoNewPrivileges=yes\nPrivateTmp=yes\nPrivateDevices=yes\nProtectSystem=strict\nProtectHome=yes\nProtectKernelTunables=yes\nProtectKernelModules=yes\nProtectControlGroups=yes\nRestrictSUIDSGID=yes\nLockPersonality=yes\nRestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\n\n[Install]\nWantedBy=multi-user.target\n"""
    SERVICE_FILE.write_text(service, encoding="utf-8")
    os.chmod(SERVICE_FILE, 0o644)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "lghs-fleet-web-cloudflared.service"], check=True, stdout=subprocess.DEVNULL)

    print(f"Fleet UI tunnel ready: {TUNNEL_NAME}")
    print(f"Hostname: {hostname}")
    print("Origin: http://127.0.0.1:8790")
    print("Connector token: stored securely (not printed)")

    if args.start:
        if not access_configured():
            raise RuntimeError("refusing to expose Fleet UI: configure Cloudflare Access values and at least one LGHS web role first")
        subprocess.run(["systemctl", "restart", "lghs-fleet-web.service"], check=True)
        subprocess.run(["systemctl", "restart", "lghs-fleet-web-cloudflared.service"], check=True)
        print("Fleet Web and dedicated Cloudflare connector started")
    else:
        print("Public connector was NOT started. Configure Cloudflare Access, then re-run with --start.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
