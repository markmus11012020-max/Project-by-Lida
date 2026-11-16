"""Build the defense video from slide screenshots and the existing voiceover.

Why: Playwright video capture can skip repaints on long slide decks. This
script captures each slide as a still image and lets ffmpeg hold it for the
exact narration duration.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx
import imageio_ffmpeg
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record_demo import _configure_stdout, _duration_ms  # noqa: E402

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = CALL_CENTER_DIR / "demo"
TTS_DIR = DEMO_DIR / "tts"
RAW_DIR = DEMO_DIR / "raw" / "defense"
FINAL_VIDEO = DEMO_DIR / "callpilot-defense.mp4"
BASE_URL = "http://127.0.0.1:8030"
DECK_URL = f"{BASE_URL}/demo/defense_slides.html"
SCENE_COUNT = 10
PAUSE_MS = 450


def _wait_for_deck(timeout: int = 30) -> bool:
    for _ in range(timeout):
        try:
            if httpx.get(DECK_URL, timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main() -> int:
    _configure_stdout()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            str(8030),
            "--bind",
            "127.0.0.1",
        ],
        cwd=str(CALL_CENTER_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_for_deck():
            print("Слайды не открылись.")
            return 1

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(
                    channel="msedge", headless=True
                )
            except Exception:
                browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1,
            )
            page.goto(DECK_URL, wait_until="networkidle")
            page.add_style_tag(
                content=(
                    "*{animation:none!important;transition:none!important;}"
                )
            )
            page.wait_for_timeout(500)
            for index in range(SCENE_COUNT):
                page.evaluate(f"showSlide({index})")
                page.wait_for_timeout(350)
                target = RAW_DIR / f"slide_{index + 1:02d}.png"
                page.screenshot(path=str(target))
                print(f"  slide {index + 1}: {target.name}")
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()

    scenes = [
        TTS_DIR / f"defense_{index:02d}.mp3"
        for index in range(1, SCENE_COUNT + 1)
    ]
    durations = [_duration_ms(path) for path in scenes]
    voiceover = TTS_DIR / "defense_voiceover.mp3"
    if not voiceover.exists():
        print("Нет defense_voiceover.mp3")
        return 1

    concat = RAW_DIR / "slides.txt"
    lines: list[str] = []
    for index, duration_ms in enumerate(durations, start=1):
        image = RAW_DIR / f"slide_{index:02d}.png"
        lines.append(f"file '{image.as_posix()}'")
        hold = duration_ms + (PAUSE_MS if index < SCENE_COUNT else 0)
        lines.append(f"duration {hold / 1000:.3f}")
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    print("Собираю MP4 из слайдов...")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-i",
            str(voiceover),
            "-fps_mode",
            "cfr",
            "-r",
            "25",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "stillimage",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(FINAL_VIDEO),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"Готово: {FINAL_VIDEO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
