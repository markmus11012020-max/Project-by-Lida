"""Record the 5-7 minute CallPilot defense video from docs/DEFENSE.md.

Run from the project root:
    .venv\\Scripts\\python.exe call-center\\scripts\\record_defense.py

Output:
    call-center/demo/callpilot-defense.mp4

Uses the same native Russian voice and punctuation pauses as the product demo.
The slide deck is call-center/demo/defense_slides.html.
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
from playwright.sync_api import sync_playwright

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = CALL_CENTER_DIR / "demo"
TTS_DIR = DEMO_DIR / "tts"
RAW_DIR = DEMO_DIR / "raw"
FINAL_VIDEO = DEMO_DIR / "callpilot-defense.mp4"
BASE_URL = "http://127.0.0.1:8030"
DECK_URL = f"{BASE_URL}/demo/defense_slides.html"

sys.path.insert(0, str(CALL_CENTER_DIR / "scripts"))
from record_demo import (  # noqa: E402
    PAUSE_MS,
    _combine,
    _concat_audio,
    _configure_stdout,
    _duration_ms,
    _make_silence,
    _split_for_tts,
    _tts_text,
)

SCENES: list[dict] = [
    {
        "id": "01",
        "slide": 0,
        "text": (
            "Здравствуйте. Это Колл-Пайлот — сервис AI-постобработки "
            "и контроля качества звонков для колл-центров. За несколько "
            "минут покажу, как звонок превращается в карточку, проходит "
            "QA-проверку и становится понятным действием для бизнеса. "
            "Разберём проблему, архитектуру, ручную проверку, результаты "
            "и экономику."
        ),
    },
    {
        "id": "02",
        "slide": 1,
        "text": (
            "Служба качества слушает только два-пять процентов звонков. "
            "Остальное — слепая зона. Оператор тратит три-четыре минуты "
            "на карточку, резюме и следующий шаг. Жалобы, возвраты "
            "и ложные обещания всплывают постфактум. Руководитель не видит "
            "полной картины. Колл-Пайлот закрывает этот разрыв."
        ),
    },
    {
        "id": "03",
        "slide": 2,
        "text": (
            "Публичное демо работает на синтетических звонках. Шесть "
            "звонков, аудио, транскрипт, QA-чек-лист и подтверждение "
            "оператором. Реальные записи на публичном стенде не принимаются. "
            "Ограничения осознанные: веб-панель, один контур, SQLite "
            "для демо, без реальной телефонии и без замены операторов. "
            "Это MVP, который можно развернуть в контуре клиента."
        ),
    },
    {
        "id": "04",
        "slide": 3,
        "text": (
            "Схема сквозная. Веб-панель отправляет запрос в API. API "
            "создаёт звонок в SQLite. AI-обработка вызывает AITUNNEL: "
            "модель DeepSeek, температура ноль-два, строгий JSON. Сервер "
            "валидирует ответ через Pydantic. Контроль качества применяет "
            "детерминированные правила. Результат пишется в call_reviews "
            "и audit_runs. Панель показывает список, карточку, QA-аналитику "
            "и журнал аудита."
        ),
    },
    {
        "id": "05",
        "slide": 4,
        "text": (
            "Главный принцип: AI не пишет в CRM без человека. Если есть "
            "critical или high нарушение, QA-score ниже восьмидесяти пяти, "
            "негативный клиент, низкая уверенность или пропущены критичные "
            "поля — система ставит need_review=true и сохраняет "
            "review_reason. Звонок попадает в очередь. Оператор слушает "
            "аудио с таймкодами, проверяет карточку и подтверждает. "
            "Пример: ложное обещание возврата. Модель находит две "
            "critical-находки, оценка ноль, причина проверки видна "
            "в карточке и в аудите."
        ),
    },
    {
        "id": "06",
        "slide": 5,
        "text": (
            "Три точки API. Первая — создать звонок: POST /api/v1/calls. "
            "Вторая — получить список: GET /api/v1/calls. Третья — "
            "AI-обработка: POST /api/v1/calls/id/process. Дополнительно "
            "есть карточка, журнал аудита и экспорт CSV или JSONL. "
            "В audit_runs хранятся действие, вход, выход, статус, ошибка, "
            "длительность и время. Это не чёрный ящик: видно, что "
            "предложила модель и что изменил человек."
        ),
    },
    {
        "id": "07",
        "slide": 6,
        "text": (
            "На входе — маскирование персональных данных, проверка "
            "транскрипта и ограничения загрузки. На выходе — парсинг JSON, "
            "Pydantic, проверка типов и диапазонов, детерминированный "
            "пересчёт QA-score. Critical и high нарушения не могут быть "
            "занижены моделью. Auto-pass только при оценке выше "
            "восьмидесяти пяти и отсутствии критичных нарушений. "
            "Невалидный ответ — fallback и ручная проверка, а не "
            "выдуманный результат."
        ),
    },
    {
        "id": "08",
        "slide": 7,
        "text": (
            "На десяти тестовых кейсах: пять auto-pass и пять ручных "
            "проверок, включая два critical-кейса. Все ответы валидны, "
            "аудит заполнен. Экономика: тысяча звонков в месяц, три минуты "
            "на карточку, двести пятнадцать рублей в час. Это пятьдесят "
            "часов рутины, сорок часов экономии, восемь тысяч шестьсот "
            "рублей в месяц. AI-разбор стоит триста тридцать рублей, "
            "чистая экономия — восемь тысяч двести семьдесят рублей. "
            "На один звонок — восемь рублей шестьдесят копеек. При десяти "
            "тысячах звонков экономия около восьмидесяти шести тысяч."
        ),
    },
    {
        "id": "09",
        "slide": 8,
        "text": (
            "Риски закрыты. Модель выдумывает факты — запрет на новые "
            "данные, missing_fields, низкая температура и ручная проверка. "
            "Невалидный JSON — Pydantic и fallback. Персональные данные — "
            "синтетика в демо, маскирование и vault. Ошибка CRM — "
            "durable-outbox и повторные попытки. Плохое аудио — confidence, "
            "ручная проверка и локальный STT. Недоверие операторов — HITL, "
            "прозрачные правки и пилот."
        ),
    },
    {
        "id": "10",
        "slide": 9,
        "text": (
            "План развития: PostgreSQL и очередь, локальный STT, on-prem, "
            "пилот на ста-трёхстах реальных звонках, метрики WER "
            "и auto-pass. CRM-адаптеры Bitrix24 и amoCRM уже готовы. Итог: "
            "работающий продукт, который принимает звонок, структурирует "
            "его, проверяет качество, эскалирует сложные случаи и хранит "
            "прозрачный аудит. Спасибо за внимание, готов ответить "
            "на вопросы."
        ),
    },
]


def _wait_for_deck(timeout: int = 30) -> bool:
    for _ in range(timeout):
        try:
            response = httpx.get(DECK_URL, timeout=2)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _synthesize_sapi(text: str, target: Path) -> None:
    """Fallback for environments where edge-tts is unavailable."""

    wav = target.with_suffix(".wav")
    txt = target.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8")
    script = f"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('Microsoft Irina Desktop')
$s.Rate = 0
$s.Volume = 100
$s.SetOutputToWaveFile('{wav.as_posix()}')
$text = Get-Content -Raw -Encoding UTF8 '{txt.as_posix()}'
$s.Speak($text)
$s.Dispose()
"""
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(wav),
            "-ar",
            "24000",
            "-ac",
            "1",
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
    wav.unlink(missing_ok=True)
    txt.unlink(missing_ok=True)


async def _synthesize_chunk(text: str, target: Path) -> None:
    if target.exists() and target.stat().st_size > 1000:
        return
    last_error: Exception | None = None
    try:
        await edge_tts.Communicate(
            text,
            "ru-RU-SvetlanaNeural",
            rate="-2%",
        ).save(str(target))
        if target.exists() and target.stat().st_size > 1000:
            return
    except Exception as exc:  # noqa: BLE001
        last_error = exc
    try:
        _synthesize_sapi(text, target)
        if target.exists() and target.stat().st_size > 1000:
            print("    edge-tts недоступен, использую Windows SAPI")
            return
    except Exception as exc:  # noqa: BLE001
        last_error = exc
    raise RuntimeError(f"Не удалось озвучить фрагмент: {last_error}")


def _build_voice(ffmpeg: str, text: str, target: Path) -> None:
    """Synthesize one scene sequentially.

    edge-tts occasionally drops a parallel request with "No audio was
    received"; sequential synthesis with retries is slower but reliable.
    """
    if target.exists() and target.stat().st_size > 1000:
        return
    chunks = _split_for_tts(_tts_text(text))
    if not chunks:
        raise RuntimeError("Пустой текст озвучки")

    part_dir = TTS_DIR / "parts" / target.stem
    part_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for index, (chunk, pause_ms) in enumerate(chunks, start=1):
        part = part_dir / f"{index:02d}.mp3"
        asyncio.run(_synthesize_chunk(chunk, part))
        files.append(part)
        if index < len(chunks) and pause_ms > 0:
            silence = TTS_DIR / f"silence_{pause_ms}.mp3"
            _make_silence(ffmpeg, silence, pause_ms)
            files.append(silence)
        if index % 5 == 0:
            print(f"    {target.name}: {index}/{len(chunks)} фраз")
    _concat_audio(ffmpeg, files, target)
    total_pause = sum(pause for _chunk, pause in chunks[:-1])
    print(f"    {target.name}: {len(chunks)} фраз, паузы {total_pause} мс")


def main() -> int:
    _configure_stdout()
    for directory in (TTS_DIR, RAW_DIR / "defense"):
        directory.mkdir(parents=True, exist_ok=True)

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    print("Генерирую защиту: озвучка с паузами...")
    voice_files: list[Path] = []
    for scene in SCENES:
        target = TTS_DIR / f"defense_{scene['id']}.mp3"
        _build_voice(ffmpeg, scene["text"], target)
        scene["duration_ms"] = _duration_ms(target)
        voice_files.append(target)
        print(
            f"  defense {scene['id']}: "
            f"{scene['duration_ms'] / 1000:.1f} c"
        )

    silence = TTS_DIR / "silence_450.mp3"
    _make_silence(ffmpeg, silence, 450)
    concat_files: list[Path] = []
    for index, file in enumerate(voice_files):
        concat_files.append(file)
        if index < len(voice_files) - 1:
            concat_files.append(silence)
    voiceover = TTS_DIR / "defense_voiceover.mp3"
    _concat_audio(ffmpeg, concat_files, voiceover)
    total = sum(scene["duration_ms"] for scene in SCENES) + 450 * (
        len(SCENES) - 1
    )
    print(f"Ожидаемая длительность: {total / 1000:.1f} c")

    print("Запускаю HTTP-сервер со слайдами...")
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            "8030",
            "--bind",
            "127.0.0.1",
        ],
        cwd=str(CALL_CENTER_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    video_path: Path | None = None
    try:
        if not _wait_for_deck():
            print("Слайды не открылись.")
            return 1

        print("Записываю видео защиты...")
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(
                    channel="msedge", headless=True
                )
            except Exception:
                browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                record_video_dir=str(RAW_DIR / "defense"),
                record_video_size={"width": 1920, "height": 1080},
            )
            page = context.new_page()
            page.goto(DECK_URL, wait_until="networkidle")
            page.wait_for_timeout(700)
            page.evaluate("showSlide(0)")
            page.wait_for_timeout(500)

            for index, scene in enumerate(SCENES, start=1):
                print(f"  slide {scene['slide'] + 1}: {scene['id']}")
                page.evaluate(f"showSlide({scene['slide']})")
                wait_ms = scene["duration_ms"] + PAUSE_MS
                page.wait_for_timeout(wait_ms)

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
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
