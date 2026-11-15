"""Audio upload validation for the V2 ingestion endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mutagen

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a"}
ALLOWED_FORMATS = {
    "MPEGInfo",
    "WaveStreamInfo",
    "OggVorbisInfo",
    "OggOpusInfo",
    "MP4Info",
    "AACInfo",
}


class AudioValidationError(ValueError):
    """Raised when an uploaded file is not a supported audio recording."""


class AudioTooLargeError(AudioValidationError):
    """Raised when an audio stream exceeds the configured limit."""


@dataclass(frozen=True)
class AudioInfo:
    filename: str
    extension: str
    size_bytes: int
    duration_ms: int
    channels: int | None
    sample_rate: int | None
    audio_format: str


def validate_audio_file(
    path: Path,
    filename: str | None = None,
    max_bytes: int = 50 * 1024 * 1024,
) -> AudioInfo:
    path = Path(path)
    display_name = filename or path.name
    extension = Path(display_name).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise AudioValidationError(
            "Поддерживаются только mp3, wav, ogg и m4a"
        )
    if not path.exists() or not path.is_file():
        raise AudioValidationError("Аудиофайл не найден")

    size = path.stat().st_size
    if size <= 0:
        raise AudioValidationError("Аудиофайл пустой")
    if size > max_bytes:
        raise AudioValidationError(
            f"Аудиофайл больше {max_bytes // (1024 * 1024)} МБ"
        )

    try:
        audio = mutagen.File(str(path))
    except Exception as exc:  # noqa: BLE001 - mutagen has many parser errors
        raise AudioValidationError("Не удалось прочитать аудиофайл") from exc

    if audio is None or getattr(audio, "info", None) is None:
        raise AudioValidationError("Формат аудио не распознан")

    info = audio.info
    duration = float(getattr(info, "length", 0) or 0)
    if duration <= 0:
        raise AudioValidationError("Не удалось определить длительность аудио")

    audio_format = type(info).__name__
    if audio_format not in ALLOWED_FORMATS:
        raise AudioValidationError(f"Неподдерживаемый формат аудио: {audio_format}")

    return AudioInfo(
        filename=display_name,
        extension=extension,
        size_bytes=size,
        duration_ms=int(duration * 1000),
        channels=getattr(info, "channels", None),
        sample_rate=getattr(info, "sample_rate", None),
        audio_format=audio_format,
    )
