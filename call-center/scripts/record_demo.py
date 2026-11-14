"""Record an automated CallPilot demo video with TTS narration.

Run from the project root:
    .venv\\Scripts\\python.exe call-center\\scripts\\record_demo.py

Output:
    call-center/demo/callpilot-demo.mp4

The script starts the app, records a browser walkthrough with Playwright,
generates scene narration with AITUNNEL TTS, and combines both with ffmpeg.
The demo database is reset after recording.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import edge_tts
import httpx
import imageio_ffmpeg
from mutagen.mp3 import MP3
from playwright.sync_api import sync_playwright

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent

DEMO_DIR = CALL_CENTER_DIR / "demo"
RAW_DIR = DEMO_DIR / "raw"
TTS_DIR = DEMO_DIR / "tts"
FINAL_VIDEO = DEMO_DIR / "callpilot-demo.mp4"
BASE_URL = "http://127.0.0.1:8020"
PAUSE_MS = 450


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _tts(text: str, target: Path) -> None:
    if target.exists() and target.stat().st_size > 1000:
        return
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            asyncio.run(
                edge_tts.Communicate(
                    text,
                    "ru-RU-SvetlanaNeural",
                    rate="-2%",
                ).save(str(target))
            )
            if target.exists() and target.stat().st_size > 1000:
                return
        except Exception as exc:
            last_error = exc
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"Native Russian TTS failed: {last_error}")


def _duration_ms(path: Path) -> int:
    return int(MP3(str(path)).info.length * 1000)


def _wait_for_server(timeout: int = 60) -> bool:
    for _ in range(timeout):
        try:
            if httpx.get(f"{BASE_URL}/health", timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _concat_audio(ffmpeg: str, files: list[Path], target: Path) -> None:
    list_file = TTS_DIR / "voiceover_concat.txt"
    lines = [
        f"file '{file.resolve().as_posix()}'" for file in files
    ]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(target),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _combine(ffmpeg: str, video: Path, voiceover: Path, target: Path) -> None:
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video),
            "-i",
            str(voiceover),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(target),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    _configure_stdout()
    for directory in (DEMO_DIR, RAW_DIR, TTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    scenes: list[dict] = [
        {
            "id": "01",
            "text": (
                "Это CallPilot — AI-контроль качества звонков для колл-центров. "
                "Обычно QA слушает только два-пять процентов звонков, а операторы "
                "тратят несколько минут на постобработку. CallPilot расшифровывает "
                "сто процентов звонков, собирает карточку, проверяет качество "
                "по чек-листу и отправляет менеджеру только нарушения и спорные случаи."
            ),
            "path": "/",
        },
        {
            "id": "02",
            "text": (
                "В демо шесть звонков. Два прошли авто-проверку, четыре требуют "
                "внимания менеджера. В очередь попадают только исключения: "
                "низкая уверенность, нарушения или спорные ситуации."
            ),
            "path": "/dashboard",
        },
        {
            "id": "03",
            "text": (
                "Откроем звонок с возвратом. Слева аудио и транскрипт, справа "
                "карточка и QA-чек-лист. Модель нашла ложное обещание возврата "
                "и критичное нарушение комплаенса."
            ),
            "path": "/calls/call_02",
        },
        {
            "id": "04",
            "text": (
                "Нажмём на цитату нарушения — плеер перемотается на нужный момент. "
                "Менеджер слышит, что именно сказал оператор, и не тратит время "
                "на поиск по записи."
            ),
            "path": None,
            "action": "quote",
        },
        {
            "id": "05",
            "text": (
                "По каждому критерию есть статус, важность, цитата и комментарий. "
                "Можно подтвердить нарушение или отменить ложное срабатывание. "
                "Оценка пересчитывается автоматически."
            ),
            "path": None,
            "action": "qa_scroll",
        },
        {
            "id": "06",
            "text": (
                "В аудите видно, что нашла модель, что подтвердил человек и какие "
                "поля изменились. Это важно для руководителя и службы качества."
            ),
            "path": None,
            "action": "audit_scroll",
        },
        {
            "id": "07",
            "text": (
                "Подтверждаем карточку. Финальная версия и все правки сохраняются "
                "в аудите и отправляются в CRM в демо-режиме."
            ),
            "path": None,
            "action": "confirm",
        },
        {
            "id": "08",
            "text": (
                "В QA-аналитике видно покрытие, auto-pass, топ нарушений "
                "и очередь менеджера. Руководитель видит не весь поток, "
                "а только исключения."
            ),
            "path": "/qa",
        },
        {
            "id": "09",
            "text": (
                "Пилот на сто-триста звонков за две недели. Показываем цифры "
                "до и после: покрытие QA, auto-pass, найденные нарушения, "
                "долю правок и экономию постобработки."
            ),
            "path": "/offer",
        },
        {
            "id": "10",
            "text": (
                "Если хотите, пришлите пять-десять обезличенных звонков. "
                "Покажем демо на ваших примерах и посчитаем экономику пилота."
            ),
            "path": "/offer",
        },
    ]

    print("Генерирую озвучку...")
    voice_files: list[Path] = []
    for scene in scenes:
        target = TTS_DIR / f"scene_{scene['id']}.mp3"
        _tts(scene["text"], target)
        scene["duration_ms"] = _duration_ms(target)
        voice_files.append(target)
        print(f"  scene {scene['id']}: {scene['duration_ms'] / 1000:.1f} c")

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    silence = TTS_DIR / "silence_450.mp3"
    if not silence.exists():
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=24000:cl=mono",
                "-t",
                "0.45",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "48k",
                str(silence),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    concat_files: list[Path] = []
    for index, file in enumerate(voice_files):
        concat_files.append(file)
        if index < len(voice_files) - 1:
            concat_files.append(silence)
    voiceover = TTS_DIR / "voiceover.mp3"
    _concat_audio(ffmpeg, concat_files, voiceover)

    print("Запускаю сервер...")
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
    video_path: Path | None = None
    try:
        if not _wait_for_server():
            print("Сервер не поднялся.")
            return 1

        print("Записываю видео...")
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(
                    channel="msedge", headless=True
                )
            except Exception:
                browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                record_video_dir=str(RAW_DIR),
                record_video_size={"width": 1440, "height": 900},
            )
            page = context.new_page()

            for scene in scenes:
                print(f"  scene {scene['id']}")
                started = time.perf_counter()
                if scene.get("path"):
                    page.goto(
                        f"{BASE_URL}{scene['path']}",
                        wait_until="networkidle",
                    )
                    page.wait_for_timeout(500)
                action = scene.get("action")
                if action == "quote":
                    quote = page.locator(".quote-link").first
                    if quote.count():
                        quote.click()
                        page.wait_for_timeout(1200)
                elif action == "qa_scroll":
                    page.locator(".qa-panel").scroll_into_view_if_needed()
                    page.wait_for_timeout(500)
                elif action == "audit_scroll":
                    page.locator(".audit-panel").scroll_into_view_if_needed()
                    page.wait_for_timeout(500)
                elif action == "confirm":
                    confirm = page.locator("#confirm-btn")
                    if confirm.count():
                        confirm.click()
                        try:
                            page.wait_for_url("**/confirmed=1", timeout=8000)
                        except Exception:
                            pass
                        page.wait_for_timeout(800)

                target_seconds = (scene["duration_ms"] + PAUSE_MS) / 1000
                elapsed = time.perf_counter() - started
                remaining = target_seconds - elapsed
                if remaining > 0:
                    page.wait_for_timeout(int(remaining * 1000))

            video = page.video
            context.close()
            browser.close()
            video_path = Path(video.path())

        if video_path is None or not video_path.exists():
            print("Видео не записалось.")
            return 1

        print(f"Собираю MP4: {FINAL_VIDEO}")
        _combine(ffmpeg, video_path, voiceover, FINAL_VIDEO)
        print(f"Готово: {FINAL_VIDEO}")
        return 0
    finally:
        httpx.post(f"{BASE_URL}/demo/reset", timeout=10)
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
