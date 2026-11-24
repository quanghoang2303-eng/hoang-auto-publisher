#!/usr/bin/env python3
"""Read-only, network-free preflight for the local Auto Publisher.

Run ``python publisher.py doctor`` (or ``python doctor.py --strict``).
No media is uploaded, OAuth refresh is not attempted, and secrets are never printed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Mapping

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
VALID_TARGETS = {"facebook", "youtube", "tiktok"}


@dataclass(frozen=True)
class Finding:
    severity: str  # OK, WARN, FAIL
    name: str
    explanation: str


def effective_config(env_file: Path = ROOT / ".env", environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Use dotenv with the same precedence as publisher.load_dotenv (environment wins)."""
    loaded = {k: v for k, v in dotenv_values(env_file).items() if v is not None}
    loaded.update(dict(os.environ if environ is None else environ))
    return loaded


def parse_targets(raw: str, supported: set[str], key: str) -> list[str]:
    targets = [v.strip() for v in raw.split(",") if v.strip()]
    if not targets or len(targets) != len(set(targets)) or not set(targets).issubset(supported):
        raise ValueError(f"{key} must contain distinct targets from {sorted(supported)}")
    return targets


def report(config: Mapping[str, str], root: Path = ROOT, *, strict: bool = False) -> list[Finding]:
    """Inspect local configuration only; never contact Facebook/YouTube/TikTok."""
    findings: list[Finding] = []

    def add(level: str, name: str, detail: str) -> None:
        findings.append(Finding(level, name, detail))

    def missing(name: str, description: str) -> None:
        add("FAIL" if strict else "WARN", name, description)

    def local_path(value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else root / p

    for binary in ("ffprobe", "ffmpeg"):
        if shutil.which(binary):
            add("OK", binary, "Installed")
        else:
            missing(binary, f"Install via `brew install ffmpeg` (includes {binary})")

    short_dir = (config.get("VIDEO_DIR") or "").strip()
    full_dir = ((config.get("FULL_VIDEO_DIR") or "").strip()
                or (config.get("YT_LONG_VIDEO_DIR") or "").strip())
    if not short_dir:
        missing("VIDEO_DIR", "Set a highlight folder in .env")
    elif local_path(short_dir).is_dir():
        add("OK", "VIDEO_DIR", "Highlight directory exists")
    else:
        missing("VIDEO_DIR", "Highlight directory does not exist; create it before publishing")
    if full_dir:
        if short_dir and local_path(full_dir).resolve() == local_path(short_dir).resolve():
            add("FAIL", "FULL_VIDEO_DIR", "Full episodes and highlights must use different directories")
        elif local_path(full_dir).is_dir():
            add("OK", "FULL_VIDEO_DIR", "Full-episode directory exists")
        else:
            missing("FULL_VIDEO_DIR", "Full-episode directory does not exist")
    else:
        add("WARN", "FULL_VIDEO_DIR", "Full-episode stream is disabled")

    selected: set[str] = set()
    for name, raw, allowed in [
        ("PLATFORMS", config.get("PLATFORMS", "facebook,youtube"), VALID_TARGETS),
        ("FULL_PLATFORMS", config.get("FULL_PLATFORMS", "youtube"), {"facebook", "youtube"}),
    ]:
        if name == "FULL_PLATFORMS" and not full_dir:
            continue
        try:
            targets = parse_targets(raw, allowed, name)
        except ValueError as exc:
            add("FAIL", name, str(exc))
        else:
            selected.update(targets)
            add("OK", name, ", ".join(targets))

    if "facebook" in selected:
        for name in ("FB_PAGE_ID", "FB_PAGE_ACCESS_TOKEN"):
            if not (config.get(name) or "").strip():
                missing(name, "Missing Facebook Page credential; store it in the local .env only")
            else:
                add("OK", name, "Configured (value hidden; validity not checked)")
        if config.get("FB_ALLOW_PUBLIC_POSTING", "false").lower() != "true":
            missing("FB_ALLOW_PUBLIC_POSTING", "Public Page publishing is OFF; explicitly enable only after testing")
        else:
            add("WARN", "FB_ALLOW_PUBLIC_POSTING", "ON: Facebook Page uploads are PUBLIC")
    if "youtube" in selected:
        for name, fallback in (("YT_CLIENT_SECRET_FILE", "client_secret.json"), ("YT_TOKEN_FILE", "token.json")):
            location = local_path(config.get(name, fallback))
            if not location.is_file():
                missing(name, "OAuth JSON file missing (contents not inspected or displayed)")
            else:
                try:
                    obj = json.loads(location.read_text(encoding="utf-8"))
                    if not isinstance(obj, dict):
                        raise ValueError("not an object")
                except (OSError, UnicodeError, ValueError):
                    add("FAIL", name, "OAuth file is unreadable or invalid JSON")
                else:
                    add("OK", name, "OAuth JSON file exists (authorization not verified)")
        for privacy in ("YT_PRIVACY", "YT_LONG_PRIVACY"):
            if privacy == "YT_LONG_PRIVACY" and not full_dir:
                continue
            v = config.get(privacy, "private" if privacy == "YT_LONG_PRIVACY" else "public")
            if v not in {"private", "unlisted", "public"}:
                add("FAIL", privacy, "Must be private, unlisted, or public")
            elif v == "public":
                add("WARN", privacy, "PUBLIC: video will be visible if platform accepts publication")
            else:
                add("OK", privacy, v)
    if "tiktok" in selected:
        mode = config.get("TIKTOK_MODE", "off").lower()
        if mode == "manual":
            add("OK", "TikTok manual", "Local review package; owner publishes or schedules in TikTok Studio")
        elif mode == "adb":
            add("FAIL", "TikTok ADB", "Unattended UI posting disabled; use manual mode")
        elif mode == "api":
            if config.get("TIKTOK_APP_APPROVED", "false").lower() != "true":
                missing("TIKTOK_APP_APPROVED", "Actual eligibility/review/audit required; do not enable just to test")
            token_path = local_path(config.get("TIKTOK_TOKEN_FILE", "state/tiktok_token.json"))
            if token_path.is_file():
                add("OK", "TIKTOK_TOKEN_FILE", "Local OAuth store exists; validity not checked")
                for key in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"):
                    if not config.get(key, "").strip():
                        missing(key, "Required for OAuth token refresh")
            elif config.get("TIKTOK_ACCESS_TOKEN", "").strip():
                add("WARN", "TIKTOK_ACCESS_TOKEN", "Legacy user token configured; automatic refresh unavailable")
            else:
                missing("TIKTOK_TOKEN_FILE", "Authorize eligible app via Login Kit first")
            add("WARN", "TikTok API", "Only for an eligible reviewed app with compliant per-video UX/consent")
        else:
            missing("TIKTOK_MODE", "TikTok target selected but mode is disabled/invalid")

    manifest = (config.get("PUBLISH_MANIFEST") or "").strip()
    if manifest:
        path = local_path(manifest)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = data.get("videos") if isinstance(data, dict) else None
            if not isinstance(entries, list) or not entries:
                raise ValueError("expected nonempty videos array")
            names: set[str] = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("manifest entries must be objects")
                name = entry.get("media_filename")
                kind = entry.get("kind")
                if not isinstance(name, str) or Path(name).name != name or name in names or kind not in {"short", "long"}:
                    raise ValueError("duplicate/invalid media_filename or kind")
                names.add(name)
                target = entry.get("allowed_targets")
                allowed = {"facebook", "youtube"} if kind == "long" else VALID_TARGETS
                if not isinstance(target, list) or not target or not set(target) <= allowed:
                    raise ValueError(f"invalid allowed_targets for {name}")
        except (OSError, UnicodeError, ValueError) as exc:
            add("FAIL", "PUBLISH_MANIFEST", f"Cannot use publishing manifest: {type(exc).__name__}")
        else:
            add("OK", "PUBLISH_MANIFEST", f"Valid JSON structure, {len(entries)} entries (metadata not fully checked)")

    if config.get("ENABLE_LIVE_POSTING", "false").lower() == "true":
        add("WARN", "ENABLE_LIVE_POSTING", "ON: scheduler can publish real videos")
    else:
        missing("ENABLE_LIVE_POSTING", "OFF: uploads are disabled (recommended for dry run)")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline, read-only publishing preflight")
    parser.add_argument("--strict", action="store_true", help="Treat missing live-publish prerequisites as errors")
    args = parser.parse_args(argv)
    conf = effective_config()
    issues = report(conf, strict=args.strict)
    for item in issues:
        print(f"[{item.severity}] {item.name}: {item.explanation}")
    total = sum(item.severity == "FAIL" for item in issues)
    print(f"Preflight: {len(issues)} checks, {total} blocking issue(s). No network requests or uploads were made.")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())