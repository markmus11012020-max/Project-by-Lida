"""Generate synthetic demo call audio.

Primary TTS: AITUNNEL gpt-4o-mini-tts (onyx for operator, nova for client).
Fallback: edge-tts Russian voices.

Run from the project root:
    .venv\\Scripts\\python.exe call-center\\scripts\\build_demo_audio.py

Outputs:
    call-center/static/audio/call_XX.mp3
    call-center/data/audio_manifest.json
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import edge_tts
import imageio_ffmpeg
from mutagen.mp3 import MP3
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from demo_data import DEMO_CALLS  # noqa: E402

CACHE_DIR = ROOT / ".cache" / "tts"
AUDIO_DIR = ROOT / "static" / "audio"
DATA_DIR = ROOT / "data"
PAUSE_MS = 350

AITUNNEL_VOICES = {
    "Оператор": "onyx",
    "Клиент": "nova",
}
AITUNNEL_INSTRUCTIONS = {
    "Оператор": "Спокойный, доброжелательный голос оператора колл-центра.",
    "Клиент": "Естественная разговорная речь клиента колл-центра.",
}
EDGE_VOICES = {
    "Оператор": "ru-RU-DmitryNeural",
    "Клиент": "ru-RU-SvetlanaNeural",
}


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _duration_ms(path: Path) -> int:
    return int(MP3(str(path)).info.length * 1000)


def _make_silence(ffmpeg: str, target: Path) -> None:
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
            "0.35",
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


def _concat(ffmpeg: str, files: list[Path], target: Path) -> None:
    list_file = CACHE_DIR / f"{target.stem}_concat.txt"
    lines = []
    for file in files:
        safe = file.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{safe}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
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
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
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


def _synthesize_aitunnel(
    client: OpenAI,
    text: str,
    speaker: str,
    target: Path,
) -> None:
    if target.exists() and target.stat().st_size > 1000:
        return
    response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice=AITUNNEL_VOICES[speaker],
        input=text,
        instructions=AITUNNEL_INSTRUCTIONS[speaker],
        response_format="mp3",
    )
    target.write_bytes(response.content)


def _synthesize_edge(text: str, speaker: str, target: Path) -> None:
    if target.exists() and target.stat().st_size > 1000:
        return
    asyncio.run(
        edge_tts.Communicate(text, EDGE_VOICES[speaker]).save(str(target))
    )


def _synthesize(
    client: OpenAI,
    text: str,
    speaker: str,
    target: Path,
) -> tuple[str, str]:
    try:
        _synthesize_aitunnel(client, text, speaker, target)
        return target.name, "aitunnel"
    except Exception as exc:
        print(f"  AITUNNEL TTS failed for {target.name}: {exc}")
        _synthesize_edge(text, speaker, target)
        return target.name, "edge"


def main() -> int:
    _configure_stdout()
    for directory in (CACHE_DIR, AUDIO_DIR, DATA_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    if not settings.llm_configured:
        print("AITUNNEL_API_KEY не настроен, будет использован edge-tts.")
    client = OpenAI(
        api_key=settings.aitunnel_api_key,
        base_url=settings.aitunnel_base_url,
    )

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    silence = CACHE_DIR / "silence_350.mp3"
    _make_silence(ffmpeg, silence)

    jobs: list[tuple[str, str, Path]] = []
    for call in DEMO_CALLS:
        for segment in call["segments"]:
            jobs.append(
                (
                    segment["text"],
                    segment["speaker"],
                    CACHE_DIR / f"{call['id']}_{segment['id']}.mp3",
                )
            )

    print(f"Генерирую {len(jobs)} реплик...")
    engines: dict[str, int] = {"aitunnel": 0, "edge": 0}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_synthesize, client, text, speaker, target)
            for text, speaker, target in jobs
        ]
        for index, future in enumerate(as_completed(futures), start=1):
            name, engine = future.result()
            engines[engine] = engines.get(engine, 0) + 1
            print(f"  [{index:02d}/{len(jobs)}] {name} ({engine})")
    print(f"Готово: {engines}")

    manifest: dict[str, dict] = {}
    for call in DEMO_CALLS:
        files: list[Path] = []
        segments_meta: list[dict] = []
        cursor_ms = 0
        for index, segment in enumerate(call["segments"]):
            segment_file = CACHE_DIR / f"{call['id']}_{segment['id']}.mp3"
            duration = _duration_ms(segment_file)
            segments_meta.append(
                {
                    "id": segment["id"],
                    "speaker": segment["speaker"],
                    "text": segment["text"],
                    "start_ms": cursor_ms,
                    "end_ms": cursor_ms + duration,
                }
            )
            files.append(segment_file)
            cursor_ms += duration
            if index < len(call["segments"]) - 1:
                files.append(silence)
                cursor_ms += PAUSE_MS

        output = AUDIO_DIR / f"{call['id']}.mp3"
        _concat(ffmpeg, files, output)
        manifest[call["id"]] = {
            "file": f"audio/{output.name}",
            "duration_ms": cursor_ms,
            "segments": segments_meta,
        }
        print(f"  {call['id']}: {cursor_ms / 1000:.1f} c -> {output.name}")

    manifest_path = DATA_DIR / "audio_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Манифест: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
