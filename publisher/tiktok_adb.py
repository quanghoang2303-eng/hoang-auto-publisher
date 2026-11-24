"""Experimental UI fallback. Calibrate against your own phone; never bypass security prompts."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

from backends import PreflightError

BASE = Path(__file__).resolve().parent


def adb(*parts: str, capture: bool = False):
    cmd = ["adb"]
    if os.getenv("TIKTOK_ADB_SERIAL"):
        cmd += ["-s", os.environ["TIKTOK_ADB_SERIAL"]]
    cmd += list(parts)
    return subprocess.run(cmd, check=True, capture_output=capture, text=capture, timeout=120)


def macro_path() -> Path:
    return BASE / os.getenv("TIKTOK_ADB_STEPS", "tiktok_steps.json")


def validate_macro() -> list[dict]:
    if os.getenv("ADB_MACRO_APPROVED", "false").lower() != "true":
        raise PreflightError("Set ADB_MACRO_APPROVED=true only after testing on your phone")
    file = macro_path()
    if not file.exists():
        raise PreflightError(f"Missing calibrated TikTok UI macro: {file}")
    sequence = json.loads(file.read_text(encoding="utf-8")).get("steps", [])
    if not sequence:
        raise PreflightError("ADB macro has no steps")
    actions = [s.get("action") for s in sequence]
    if actions.count("publish_text") != 1 or actions[-1] != "publish_text":
        raise PreflightError("ADB macro must have exactly one final publish_text step")
    if "assert_text" not in actions[:-1]:
        raise PreflightError("ADB macro needs assert_text before final publish action")
    allowed = {"sleep", "tap_text", "tap_desc", "tap_xy", "set_text", "assert_text", "publish_text"}
    if not set(actions) <= allowed:
        raise PreflightError(f"Unsupported ADB actions: {set(actions) - allowed}")
    return sequence


def get_device():
    import uiautomator2 as u2

    device = u2.connect(os.getenv("TIKTOK_ADB_SERIAL") or None)
    if not device.info.get("screenOn", True):
        raise PreflightError("Android screen is off")
    return device


def inspect():
    import uiautomator2 as u2

    print("ADB devices:")
    adb("devices")
    device = u2.connect(os.getenv("TIKTOK_ADB_SERIAL") or None)
    save_to = BASE / "state"
    save_to.mkdir(exist_ok=True)
    screenshot = save_to / "adb_screen.png"
    device.screenshot(str(screenshot))
    print("Screenshot:", screenshot)
    xml = device.dump_hierarchy()
    root = ET.fromstring(xml)
    for node in root.iter("node"):
        title = node.get("text") or node.get("content-desc") or ""
        if title:
            print(f"  {title[:75]!r} | {node.get('resource-id', '')} | {node.get('bounds', '')}")


def click_one(selector, text: str):
    if not selector.exists(timeout=7):
        raise RuntimeError(f"Element not found: {text}; UI likely changed")
    selector.click()
    time.sleep(1.5)


def publish(video: Path, caption: str) -> tuple[str, str]:
    """Return submitted_unverified; the Android UI has no reliable publish ID."""
    steps = validate_macro()  # fail closed before touching the device
    device = get_device()
    dest = f"/sdcard/Movies/AutoPublisher/{video.stem[:35]}-{int(time.time())}.mp4"
    adb("shell", "mkdir", "-p", "/sdcard/Movies/AutoPublisher")
    adb("push", str(video), dest)
    adb("shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", "file://" + dest)
    device.app_start(os.getenv("TIKTOK_PACKAGE", "com.zhiliaoapp.musically"), stop=True)
    time.sleep(4)
    try:
        for step in steps:
            action = step["action"]
            if action == "sleep":
                time.sleep(min(30, max(0, float(step.get("seconds", 2)))))
            elif action in {"tap_text", "assert_text", "publish_text"}:
                value = step["text"]
                target = device(text=value)
                if action == "assert_text":
                    if not target.exists(timeout=7):
                        raise RuntimeError(f"Expected screen label missing: {value}")
                else:
                    click_one(target, value)
            elif action == "tap_desc":
                click_one(device(description=step["text"]), step["text"])
            elif action == "tap_xy":
                width, height = device.window_size()
                x, y = int(step["x"]), int(step["y"])
                if not (0 <= x < width and 0 <= y < height):
                    raise RuntimeError(f"Tap coordinates {x,y} outside screen {width,height}")
                device.click(x, y)
                time.sleep(1.5)
            elif action == "set_text":
                target = device(**step["selector"])
                if not target.exists(timeout=7):
                    raise RuntimeError("Caption input not found")
                target.set_text(step.get("value", "{caption}").replace("{caption}", caption))
            else:
                raise RuntimeError("Unrecognized TikTok macro action")
    except Exception:
        output = BASE / "state" / f"adb_failure_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        try:
            device.screenshot(str(output))
            print(f"Saved Android debug screenshot: {output}")
        except Exception:
            pass
        raise
    return "submitted_unverified", "adb-no-post-id"