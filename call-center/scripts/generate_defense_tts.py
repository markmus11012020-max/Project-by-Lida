"""Generate the defense narration with the same voice as the product demo.

Uses AITUNNEL `mai-voice-2` with Microsoft `ru-RU-SvetlanaNeural` —
the same voice family as edge-tts in `callpilot-demo.mp4`.
The text is split into phrases with the same punctuation pauses as the
original recorder. The final video builder calibrates the overall tempo
to 5:35 — 15% faster than the original 6:34 defense.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx
import imageio_ffmpeg

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CALL_CENTER_DIR / "scripts"))
sys.path.insert(0, str(CALL_CENTER_DIR.parent))

from record_defense import SCENES  # noqa: E402
from record_demo import (  # noqa: E402
    _configure_stdout,
    _duration_ms,
    _make_silence,
    _split_for_tts,
    _tts_text,
)

TTS_DIR = CALL_CENTER_DIR / "demo" / "tts"
VOICEOVER = TTS_DIR / "defense_voiceover.mp3"
PAUSE_MS = 450
MODEL = "mai-voice-2"
VOICE = "ru-RU-SvetlanaNeural"


def _speech_text(text: str) -> str:
    replacements = [
        ("POST /api/v1/calls/id/process", "POST, API, v1, calls, process"),
        ("POST /api/v1/calls", "POST, API, v1, calls"),
        ("GET /api/v1/calls", "GET, API, v1, calls"),
        ("audit_runs", "audit runs"),
        ("need_review", "need review"),
        ("review_reason", "review reason"),
        ("call_reviews", "call reviews"),
        ("call_center", "call center"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return _tts_text(text)


def _api_key() -> str:
    from app.config import get_settings

    key = get_settings().aitunnel_api_key.strip()
    if not key:
        raise SystemExit("AITUNNEL_API_KEY не задан")
    return key


def _tts(
    client: httpx.Client,
    headers: dict[str, str],
    text: str,
    target: Path,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 1000:
        return
    last_error = ""
    for attempt in range(1, 6):
        try:
            response = client.post(
                "https://api.aitunnel.ru/v1/audio/speech",
                headers=headers,
                json={
                    "model": MODEL,
                    "voice": VOICE,
                    "input": text,
                    "response_format": "mp3",
                },
                timeout=60,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(2 * attempt)
            continue
        if response.status_code == 200 and response.content:
            target.write_bytes(response.content)
            time.sleep(0.6)
            return
        last_error = f"{response.status_code}: {response.text[:200]}"
        if response.status_code in {429, 500, 502, 503, 504}:
            time.sleep(2 * attempt)
        else:
            time.sleep(1)
    raise RuntimeError(last_error)


def _concat(
    ffmpeg: str,
    files: list[Path],
    target: Path,
) -> None:
    list_file = TTS_DIR / f"{target.stem}_concat.txt"
    lines = [f"file '{file.resolve().as_posix()}'" for file in files]
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
            "-ar",
            "24000",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "64k",
            str(target),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    _configure_stdout()
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    headers = {"Authorization": f"Bearer {_api_key()}"}
    scene_files: list[Path] = []

    with httpx.Client(timeout=180) as client:
        for scene in SCENES:
            chunks = _split_for_tts(_speech_text(scene["text"]))
            files: list[Path] = []
            part_dir = TTS_DIR / "parts" / f"defense_{scene['id']}"
            part_dir.mkdir(parents=True, exist_ok=True)
            for index, (chunk, pause_ms) in enumerate(chunks, start=1):
                part = part_dir / f"{index:02d}.mp3"
                _tts(client, headers, chunk, part)
                files.append(part)
                if pause_ms and index < len(chunks):
                    silence = TTS_DIR / f"silence_{pause_ms}.mp3"
                    _make_silence(ffmpeg, silence, pause_ms)
                    files.append(silence)
            scene_file = TTS_DIR / f"defense_{scene['id']}.mp3"
            _concat(ffmpeg, files, scene_file)
            scene_files.append(scene_file)
            print(
                f"  defense_{scene['id']}.mp3: "
                f"{_duration_ms(scene_file) / 1000:.1f} c"
            )

    final_files: list[Path] = []
    silence = TTS_DIR / f"silence_{PAUSE_MS}.mp3"
    _make_silence(ffmpeg, silence, PAUSE_MS)
    for index, scene_file in enumerate(scene_files):
        final_files.append(scene_file)
        if index < len(scene_files) - 1:
            final_files.append(silence)
    _concat(ffmpeg, final_files, VOICEOVER)
    print(f"Готово: {VOICEOVER} ({_duration_ms(VOICEOVER) / 1000:.1f} c)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
