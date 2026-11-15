"""Streaming upload helpers for audio ingestion."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import UploadFile

from app.audio.validation import (
    ALLOWED_EXTENSIONS,
    AudioTooLargeError,
    AudioValidationError,
)


async def save_upload_to_temp(
    upload: UploadFile,
    max_bytes: int,
    temp_dir: Path | None = None,
) -> Path:
    filename = upload.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise AudioValidationError(
            "Поддерживаются только mp3, wav, ogg и m4a"
        )

    target: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
            dir=str(temp_dir) if temp_dir else None,
        ) as handle:
            target = Path(handle.name)
            total = 0
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise AudioTooLargeError(
                        f"Аудиофайл больше {max_bytes // (1024 * 1024)} МБ"
                    )
                handle.write(chunk)
        if total <= 0:
            raise AudioValidationError("Аудиофайл пустой")
        return target
    except Exception:
        if target is not None:
            target.unlink(missing_ok=True)
        raise
