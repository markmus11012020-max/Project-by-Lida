"""Encryption-at-rest for real call recordings."""

from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class AudioVaultError(RuntimeError):
    """Raised when an audio file cannot be encrypted or decrypted."""


class AudioVault:
    def __init__(self, secret: str) -> None:
        if not secret.strip():
            raise ValueError("Audio encryption key is required")
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    @classmethod
    def from_settings(cls, settings, key_path: Path | None = None) -> "AudioVault":
        secret = settings.audio_encryption_key.strip()
        if secret:
            return cls(secret)

        if settings.pii_vault_key.strip():
            return cls(settings.pii_vault_key)

        path = Path(key_path or settings.audio_key_path)
        if path.exists():
            secret = path.read_text(encoding="utf-8").strip()
            if secret:
                return cls(secret)

        # Development fallback. Production must set AUDIO_ENCRYPTION_KEY or
        # PII_VAULT_KEY; the derived key is stable for the same secret.
        logger.warning(
            "AUDIO_ENCRYPTION_KEY is not set; using a development key"
        )
        return cls("callpilot-development-audio-key")

    def encrypt_bytes(self, data: bytes) -> bytes:
        return self._fernet.encrypt(data)

    def decrypt_bytes(self, token: bytes) -> bytes:
        try:
            return self._fernet.decrypt(token)
        except InvalidToken as exc:
            raise AudioVaultError("Не удалось расшифровать аудио") from exc

    def encrypt_file(self, source: Path, target: Path) -> Path:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.encrypt_bytes(Path(source).read_bytes()))
        return target

    def decrypt_file(self, source: Path) -> bytes:
        return self.decrypt_bytes(Path(source).read_bytes())
