"""Record an automated CallPilot demo video with TTS narration.

Run from the project root:
    .venv\\Scripts\\python.exe call-center\\scripts\\record_demo.py

Output:
    call-center/demo/callpilot-demo.mp4

The script starts the app, records a browser walkthrough with Playwright,
generates scene narration with native Russian edge-tts (with intonation pauses
at punctuation), and combines both with ffmpeg.
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

# Natural Russian intonation pauses. Commas are NOT split into separate
# chunks: edge-tts handles them naturally, without a long artificial pause.
PAUSE_BY_MARK = {
    ".": 260,
    "!": 320,
    "?": 320,
    "…": 380,
    ";": 220,
    ":": 220,
    "dash": 160,
}


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _tts_text(text: str) -> str:
    """Text for the voice, not for the screen.

    The brand must sound like «КоллПайлот», not like an English word.
    """

    return (
        text.replace("CallPilot", "КоллПайлот")
        .replace("AI-контроль", "ИИ-контроль")
    )


def _split_for_tts(text: str) -> list[tuple[str, int]]:
    """Split narration into clauses at strong punctuation only.

    Commas stay inside the phrase: edge-tts reads them with natural Russian
    intonation. Explicit pauses are added only at sentence/dash/colon boundaries.
    """

    chunks: list[tuple[str, int]] = []
    buffer: list[str] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        # A spaced dash is a separate intonation pause.
        if (
            char in "—–"
            and index > 0
            and text[index - 1].isspace()
            and index + 1 < length
            and text[index + 1].isspace()
        ):
            chunk = "".join(buffer).strip()
            if chunk:
                chunks.append((chunk, PAUSE_BY_MARK["dash"]))
            buffer = []
            index += 1
            while index < length and text[index].isspace():
                index += 1
            continue

        buffer.append(char)
        if char in ".!?…;:":
            cursor = index + 1
            while cursor < length and text[cursor] in "»”’\"')]":
                buffer.append(text[cursor])
                cursor += 1
            if cursor >= length or text[cursor].isspace():
                chunk = "".join(buffer).strip()
                if chunk:
                    chunks.append((chunk, PAUSE_BY_MARK.get(char, 0)))
                buffer = []
                index = cursor
                while index < length and text[index].isspace():
                    index += 1
                continue
        index += 1

    tail = "".join(buffer).strip()
    if tail:
        chunks.append((tail, 0))
    return chunks


def _make_silence(ffmpeg: str, target: Path, duration_ms: int) -> None:
    if target.exists() and target.stat().st_size > 1000:
        return
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            f"{duration_ms / 1000:.3f}",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "48k",
            str(target),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def _synthesize_chunk(
    text: str,
    target: Path,
    semaphore: asyncio.Semaphore,
) -> None:
    if target.exists() and target.stat().st_size > 1000:
        return
    async with semaphore:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                await edge_tts.Communicate(
                    text,
                    "ru-RU-SvetlanaNeural",
                    rate="-2%",
                ).save(str(target))
                if target.exists() and target.stat().st_size > 1000:
                    return
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(1.5 * attempt)
        raise RuntimeError(f"Native Russian TTS failed for {target.name}: {last_error}")


async def _build_scene_audio(
    ffmpeg: str,
    text: str,
    target: Path,
) -> None:
    if target.exists() and target.stat().st_size > 1000:
        return
    chunks = _split_for_tts(_tts_text(text))
    if not chunks:
        raise RuntimeError("Empty TTS text")

    semaphore = asyncio.Semaphore(3)
    part_dir = TTS_DIR / "parts" / target.stem
    part_dir.mkdir(parents=True, exist_ok=True)

    async def synth(index: int, chunk: str) -> Path:
        part = part_dir / f"{index:02d}.mp3"
        await _synthesize_chunk(chunk, part, semaphore)
        return part

    parts = await asyncio.gather(
        *[
            synth(index, chunk)
            for index, (chunk, _pause) in enumerate(chunks, start=1)
        ]
    )

    files: list[Path] = []
    for index, ((_chunk, pause_ms), part) in enumerate(zip(chunks, parts)):
        files.append(part)
        if index < len(chunks) - 1 and pause_ms > 0:
            silence = TTS_DIR / f"silence_{pause_ms}.mp3"
            _make_silence(ffmpeg, silence, pause_ms)
            files.append(silence)

    _concat_audio(ffmpeg, files, target)
    total_pause = sum(pause for _chunk, pause in chunks[:-1])
    print(
        f"    {target.name}: {len(chunks)} фраз, "
        f"паузы {total_pause} мс"
    )


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
    list_file = TTS_DIR / f"{target.stem}_concat.txt"
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
                "Это КоллПайлот — система контроля качества звонков для колл-центров. "
                "Обычно служба качества слушает только два-пять процентов звонков, "
                "а операторы тратят несколько минут на постобработку. "
                "КоллПайлот расшифровывает сто процентов звонков, собирает карточку, "
                "проверяет качество по чек-листу и отправляет менеджеру только "
                "нарушения и спорные случаи."
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
                "карточка и чек-лист качества. Модель нашла ложное обещание возврата "
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
                "В аналитике качества видно покрытие, авто-проверку, топ нарушений "
                "и очередь менеджера. Руководитель видит не весь поток, "
                "а только исключения."
            ),
            "path": "/qa",
        },
        {
            "id": "09",
            "text": (
                "Пилот на сто-триста звонков за две недели. Показываем цифры "
                "до и после: покрытие проверкой качества, авто-проверку, "
                "найденные нарушения, долю правок и экономию постобработки."
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

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    print("Генерирую озвучку с паузами на знаках препинания...")
    voice_files: list[Path] = []
    for scene in scenes:
        target = TTS_DIR / f"scene_{scene['id']}.mp3"
        asyncio.run(
            _build_scene_audio(ffmpeg, scene["text"], target)
        )
        scene["duration_ms"] = _duration_ms(target)
        voice_files.append(target)
        print(f"  scene {scene['id']}: {scene['duration_ms'] / 1000:.1f} c")

    silence = TTS_DIR / "silence_450.mp3"
    _make_silence(ffmpeg, silence, 450)
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
