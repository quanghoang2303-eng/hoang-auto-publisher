"""TikTok OAuth user-token store for an eligible reviewed integration.

Initial authorization must occur through the app's registered Login Kit flow.
Import its token response locally via stdin; never put tokens in shell arguments.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time

import requests

from backends import PreflightError

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


def token_path() -> Path:
    return Path(os.getenv("TIKTOK_TOKEN_FILE", "state/tiktok_token.json")).expanduser().resolve()


def normalize(response: dict, *, now: float | None = None, previous: dict | None = None) -> dict:
    if not isinstance(response, dict):
        raise PreflightError("Invalid TikTok OAuth response")
    now = time.time() if now is None else now
    try:
        data = {k: response[k] for k in ("access_token", "refresh_token", "open_id", "scope")}
        if any(not isinstance(v, str) or not v.strip() for v in data.values()):
            raise ValueError
        expires = int(response["expires_in"])
        refresh_expires = int(response["refresh_expires_in"])
        if expires <= 0 or refresh_expires <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise PreflightError("TikTok OAuth response is incomplete; authorize again") from exc
    if "video.publish" not in data["scope"].replace(",", " ").split():
        raise PreflightError("TikTok OAuth is missing video.publish scope")
    if previous and previous["open_id"] != data["open_id"]:
        raise PreflightError("TikTok OAuth account changed during refresh; stop and reauthorize")
    data["expires_at"] = now + expires
    data["refresh_expires_at"] = now + refresh_expires
    return data


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".tt-token-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load(path: Path) -> dict:
    try:
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise PreflightError("TikTok token file must be private (chmod 600)")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        for key in ("access_token", "refresh_token", "open_id", "scope"):
            if not isinstance(data[key], str) or not data[key].strip():
                raise ValueError
        for key in ("expires_at", "refresh_expires_at"):
            if not isinstance(data[key], (int, float)):
                raise ValueError
        if "video.publish" not in data["scope"].replace(",", " ").split():
            raise PreflightError("TikTok OAuth is missing video.publish scope")
        return data
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise PreflightError("TikTok token file missing or invalid; authorize via Login Kit") from exc


def access_token(*, now: float | None = None) -> str:
    now = time.time() if now is None else now
    path = token_path()
    if not path.exists():
        # Existing manual token configuration remains supported; it cannot refresh.
        legacy = os.getenv("TIKTOK_ACCESS_TOKEN", "").strip()
        if legacy:
            return legacy
        raise PreflightError("No TikTok OAuth user token; authorize the approved app first")
    data = load(path)
    if data["expires_at"] > now + 120:
        return data["access_token"]
    if data["refresh_expires_at"] <= now:
        raise PreflightError("TikTok refresh token expired; authorize again")
    key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
    secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
    if not key or not secret:
        raise PreflightError("TikTok OAuth refresh needs local TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET")
    try:
        response = requests.post(TOKEN_URL, data={
            "client_key": key, "client_secret": secret, "grant_type": "refresh_token",
            "refresh_token": data["refresh_token"],
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30,
            allow_redirects=False)
        response.raise_for_status()
        refreshed = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise PreflightError("TikTok OAuth refresh failed; inspect the authorized app locally") from exc
    updated = normalize(refreshed, now=now, previous=data)
    save(path, updated)
    return updated["access_token"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Import an authorized TikTok OAuth response from stdin")
    parser.add_argument("command", choices=["import-response"])
    args = parser.parse_args()
    if args.command == "import-response":
        try:
            if sys.stdin.isatty():
                raise PreflightError("Supply the OAuth response via stdin from a private local file")
            response = json.load(sys.stdin)
            save(token_path(), normalize(response))
        except (OSError, ValueError, PreflightError) as exc:
            print("TikTok OAuth import failed; check scope, expiry fields and local permissions", file=sys.stderr)
            return 1
        print("TikTok OAuth token saved locally (values hidden).")
    return 0


if __name__ == "__main__":
    from dotenv import load_dotenv
    os.chdir(Path(__file__).resolve().parent)
    load_dotenv()
    sys.exit(main())
