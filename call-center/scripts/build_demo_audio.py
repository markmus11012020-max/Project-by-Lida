"""Generate synthetic demo call audio with native Russian edge-tts voices.

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
from pathlib import Path

import edge_tts
import imageio_ffmpeg
from mutagen.mp3 import MP3

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demo_data import DEMO_CALLS  # noqa: E402

CACHE_DIR = ROOT / ".cache" / "tts"
AUDIO_DIR = ROOT / "static" / "audio"
DATA_DIR = ROOT / "data"
PAUSE_MS = 350

# Native Russian voices only. No English-accented fallbacks.
VOICES = {
    "Оператор": "ru-RU-DmitryNeural",
    "Клиент": "ru-RU-SvetlanaNeural",
}
FALLBACK_VOICES = {
    "Оператор": "ru-RU-SvetlanaNeural",
    "Клиент": "ru-RU-SvetlanaNeural",
}


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


async def _synthesize(
    text: str,
    speaker: str,
    target: Path,
    semaphore: asyncio.Semaphore,
) -> str:
    if target.exists() and target.stat().st_size > 1000:
        return "cached"

    async with semaphore:
        last_error: Exception | None = None
        voice = VOICES[speaker]
        for attempt in range(1, 6):
            try:
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(str(target))
                if target.exists() and target.stat().st_size > 1000:
                    return voice
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(1.2 * attempt)

        # Fallback: still native Russian, slightly lower/slower operator voice.
        fallback = FALLBACK_VOICES[speaker]
        rate = "-6%" if speaker == "Оператор" else "+2%"
        pitch = "-18Hz" if speaker == "Оператор" else "+2Hz"
        for attempt in range(1, 4):
            try:
                communicate = edge_tts.Communicate(
                    text, fallback, rate=rate, pitch=pitch
                )
                await communicate.save(str(target))
                if target.exists() and target.stat().st_size > 1000:
                    return fallback
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(1.2 * attempt)

    raise RuntimeError(f"TTS failed for {target.name}: {last_error}")


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


async def main() -> int:
    _configure_stdout()
    for directory in (CACHE_DIR, AUDIO_DIR, DATA_DIR):
        directory.mkdir(parents=True, exist_ok=True)

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

    print(f"Генерирую {len(jobs)} реплик русскими голосами edge-tts...")
    semaphore = asyncio.Semaphore(2)
    tasks = [
        _synthesize(text, speaker, target, semaphore)
        for text, speaker, target in jobs
    ]
    results = await asyncio.gather(*tasks)
    for index, (voice, (text, speaker, target)) in enumerate(
        zip(results, jobs), start=1
    ):
        print(f"  [{index:02d}/{len(jobs)}] {target.name} ({voice})")

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
    raise SystemExit(asyncio.run(main()))
