"""Audio ingestion and speech-to-text primitives."""

from app.audio.stt import (
    STTClient,
    STTError,
    STTResult,
    STTSegment,
    speaker_label,
    transcript_text,
)
from app.audio.download import (
    AudioURLValidationError,
    DownloadedAudio,
    download_audio_url,
    validate_audio_url,
)
from app.audio.validation import (
    ALLOWED_EXTENSIONS,
    MIME_BY_EXTENSION,
    AudioInfo,
    AudioTooLargeError,
    AudioValidationError,
    mime_for_extension,
    validate_audio_file,
)
from app.audio.upload import save_upload_to_temp
from app.audio.vault import AudioVault, AudioVaultError

__all__ = [
    "ALLOWED_EXTENSIONS",
    "AudioInfo",
    "AudioTooLargeError",
    "AudioURLValidationError",
    "AudioValidationError",
    "AudioVault",
    "AudioVaultError",
    "DownloadedAudio",
    "MIME_BY_EXTENSION",
    "STTClient",
    "STTError",
    "STTResult",
    "STTSegment",
    "download_audio_url",
    "mime_for_extension",
    "save_upload_to_temp",
    "speaker_label",
    "transcript_text",
    "validate_audio_file",
    "validate_audio_url",
]
