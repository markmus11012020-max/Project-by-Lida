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
            "Здравствуйте. Это КоллПайлот — автоматизация процесса с LLM "
            "от входа до действия. За несколько минут покажу, как входящий "
            "текст превращается в структурированный результат, проходит "
            "контроль качества и становится понятным действием для бизнеса. "
            "Разберём проблему, архитектуру, результаты и план развития."
        ),
    },
    {
        "id": "02",
        "slide": 1,
        "text": (
            "Малый бизнес получает обращения, лиды и документы в разных "
            "каналах. Сотрудник вручную читает текст, вытаскивает данные "
            "и переносит в таблицу. На одно обращение уходит около шести "
            "минут. При потоке в сотни сообщений это часы рутины и ошибки, "
            "а прозрачности нет. Служба качества слушает только два-пять "
            "процентов звонков, жалобы всплывают постфактум. MVP "
            "автоматизирует участок: принимает вход, структурирует его, "
            "проверяет качество и сохраняет результат. Сложные случаи "
            "эскалируются человеку."
        ),
    },
    {
        "id": "03",
        "slide": 2,
        "text": (
            "Клиент — небольшой бизнес, до пятисот входящих в сутки. "
            "На выходе — карточка с категорией, резюме, приоритетом "
            "и следующим действием. Ограничения осознанные: один вход "
            "через API, одно действие — запись в базу, без CRM "
            "и авторизации. Это MVP, а не готовый сервис. Задание "
            "предлагает один сценарий. Я сделал основной сценарий A, "
            "поддержку, и конфигурации B и C: продажи и документы. "
            "Один конвейер, три схемы."
        ),
    },
    {
        "id": "04",
        "slide": 3,
        "text": (
            "Схема простая. Клиент отправляет запрос на вход. Реестр "
            "сценариев выбирает промпт. Внешний LLM-сервис возвращает "
            "JSON в строгом режиме с температурой ноль-два. Сервер "
            "разбирает ответ и валидирует по схеме. Контроль качества "
            "проверяет низкую уверенность, критичные поля, несогласованную "
            "оценку и пустые поля. Результат пишется в журнал "
            "и бизнес-таблицу. Важно: я не доверяю модели. Код проверяет "
            "типы, перечисления, диапазоны и бизнес-правила. Невалидный "
            "ответ — резервный результат и передача оператору."
        ),
    },
    {
        "id": "05",
        "slide": 4,
        "text": (
            "Контроль качества — главная часть. Модель проверяет десять "
            "критериев: скрипт, комплаенс, эмпатию, решение. Уровень важности "
            "берётся из чек-листа, а не из ответа модели. Если оценка ниже "
            "восьмидесяти пяти, есть критичное нарушение или низкая уверенность — "
            "ручная проверка. Чистые кейсы проходят автоматически. Всё "
            "пишется в аудит: вход, ответ, результат и статус. Человек "
            "подтверждает финальную версию и видит правки."
        ),
    },
    {
        "id": "06",
        "slide": 5,
        "text": (
            "На тридцати тестовых кейсах: тридцать валидных результатов, "
            "ноль невалидных ответов и ошибок, двадцать автоматически, "
            "десять вручную. Это шестьдесят шесть и семь десятых процента "
            "автоматизации. Стоимость — два рубля четыре копейки, средняя "
            "задержка — три и четыре секунды. В журнале видно, почему "
            "каждый кейс обработан или эскалирован. Это прозрачный процесс, "
            "а не чёрный ящик."
        ),
    },
    {
        "id": "07",
        "slide": 6,
        "text": (
            "На базе этого модуля собран КоллПайлот для колл-центров. "
            "Он расшифровывает звонки, собирает карточку, показывает аудио "
            "с таймкодами и чек-лист качества. Менеджер видит только нарушения "
            "и спорные случаи, а не весь поток. Полное покрытие "
            "контроля качества и десять критериев. В демо шесть звонков: "
            "два автоматически, четыре на ручную проверку."
        ),
    },
    {
        "id": "08",
        "slide": 7,
        "text": (
            "Экономика: вручную тридцать кейсов — сто восемьдесят минут, "
            "с автоматизацией — шестьдесят. Экономия — сто двадцать минут, "
            "или шестьдесят шесть и семь десятых процента. Основная ценность — "
            "время менеджера и прозрачность, а не экономия на токенах. "
            "Пилот — сто-триста звонков за две недели, с замером до и после."
        ),
    },
    {
        "id": "09",
        "slide": 8,
        "text": (
            "Риски закрыты. Модель выдумывает факты — в промпте запрещено "
            "добавлять данные, которых нет во входе, обязателен список "
            "отсутствующих полей и низкая температура. Невалидный ответ — "
            "строгий режим, валидация по схеме, повтор при обрезке, "
            "резервный результат и эскалация. Ошибка в оценке лида — "
            "диапазоны и согласованность с категорией. Персональные "
            "данные — синтетика в демо, секреты вне репозитория, маскирование "
            "во второй версии. Решение принимает человек."
        ),
    },
    {
        "id": "10",
        "slide": 9,
        "text": (
            "План второй версии: надёжная база данных и очередь задач, "
            "интеграции с CRM и телефонией, маскирование персональных данных, "
            "публичный демо-стенд и метрики на реальных данных. Итог: "
            "работающий MVP, который принимает вход, структурирует его "
            "через модель, контролирует качество, эскалирует сложные случаи "
            "и хранит прозрачный аудит. На его базе сделано приложение "
            "КоллПайлот для колл-центров: полное покрытие контроля качества, "
            "аудио с таймкодами, ручная проверка только исключений "
            "и готовый оффер. Спасибо за внимание, готов ответить "
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


async def _synthesize_chunk(text: str, target: Path) -> None:
    if target.exists() and target.stat().st_size > 1000:
        return
    last_error: Exception | None = None
    for attempt in range(1, 7):
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
        await asyncio.sleep(min(2 * attempt, 10))
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
