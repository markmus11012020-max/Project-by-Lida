"""Capture product screenshots for the offer and outreach.

Run from the project root:
    .venv\\Scripts\\python.exe call-center\\scripts\\screenshots.py

Starts CallPilot on port 8020, captures pages with Playwright (Edge),
then stops the server.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CALL_CENTER_DIR.parent
SCREENSHOTS = CALL_CENTER_DIR / "screenshots"
BASE_URL = "http://127.0.0.1:8020"


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _wait_for_server(timeout: int = 60) -> bool:
    for _ in range(timeout):
        try:
            response = httpx.get(f"{BASE_URL}/health", timeout=2)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main() -> int:
    _configure_stdout()
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)

    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "call_center_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8020",
        ],
        cwd=str(CALL_CENTER_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_for_server():
            print("Сервер не поднялся.")
            return 1

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(
                    channel="msedge", headless=True
                )
            except Exception:
                browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1440, "height": 1000},
                device_scale_factor=1,
            )

            pages = [
                ("landing.png", "/", True),
                ("dashboard.png", "/dashboard", True),
                ("call_detail.png", "/calls/call_02", True),
                ("qa.png", "/qa", True),
                ("offer.png", "/offer", True),
            ]
            for filename, path, full_page in pages:
                print(f"Снимаю {path} -> {filename}")
                page.goto(f"{BASE_URL}{path}", wait_until="networkidle")
                page.wait_for_timeout(700)
                page.screenshot(
                    path=str(SCREENSHOTS / filename),
                    full_page=full_page,
                )

            # A compact hero image for social posts / Telegram.
            page.goto(f"{BASE_URL}/", wait_until="networkidle")
            page.wait_for_timeout(500)
            page.screenshot(
                path=str(SCREENSHOTS / "landing_hero.png"),
                clip={"x": 0, "y": 0, "width": 1440, "height": 900},
            )

            browser.close()
        print(f"Готово: {SCREENSHOTS}")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
