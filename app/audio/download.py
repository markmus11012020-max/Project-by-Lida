"""Safe download of an audio file by URL.

The URL path is a classic SSRF surface: validate the scheme, host, resolved
IPs and redirects before reading the body. Redirects are disabled in the
pilot implementation: the caller must provide a direct HTTPS URL.
"""

from __future__ import annotations

import ipaddress
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from app.audio.validation import AudioTooLargeError, AudioValidationError

Resolver = Callable[..., list[tuple]]

_ALLOWED_CONTENT_TYPES = (
    "audio/",
    "application/octet-stream",
    "binary/octet-stream",
)


class AudioURLValidationError(AudioValidationError):
    """Raised when an audio URL is unsafe or unsupported."""


@dataclass(frozen=True)
class DownloadedAudio:
    path: Path
    filename: str
    content_type: str
    size_bytes: int


def validate_audio_url(
    url: str,
    allowlist: str = "",
    resolver: Resolver = socket.getaddrinfo,
) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        raise AudioURLValidationError("audio_url должен использовать HTTPS")
    if parsed.username or parsed.password:
        raise AudioURLValidationError("URL с логином и паролем запрещён")
    if not parsed.hostname:
        raise AudioURLValidationError("В URL не указан домен")
    try:
        port = parsed.port
    except ValueError as exc:
        raise AudioURLValidationError("Некорректный порт в URL") from exc
    if port not in (None, 443):
        raise AudioURLValidationError("Разрешён только порт 443")

    host = parsed.hostname.lower()
    allowed = {
        item.strip().lower()
        for item in allowlist.split(",")
        if item.strip()
    }
    if allowed and not any(
        host == item or host.endswith("." + item) for item in allowed
    ):
        raise AudioURLValidationError("Домен не входит в allowlist")

    try:
        infos = resolver(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise AudioURLValidationError("Не удалось разрешить домен") from exc

    if not infos:
        raise AudioURLValidationError("Домен не разрешается в IP")

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise AudioURLValidationError("Некорректный IP домена") from exc
        if not ip.is_global:
            raise AudioURLValidationError(
                "Приватные, локальные и служебные IP запрещены"
            )

    return url.strip()


def download_audio_url(
    url: str,
    max_bytes: int,
    allowlist: str = "",
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
    resolver: Resolver = socket.getaddrinfo,
) -> DownloadedAudio:
    validate_audio_url(url, allowlist=allowlist, resolver=resolver)

    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix not in {".mp3", ".wav", ".ogg", ".m4a"}:
        suffix = ".bin"

    target: Path | None = None
    try:
        with httpx.Client(
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        ) as client:
            with client.stream("GET", url) as response:
                if 300 <= response.status_code < 400:
                    raise AudioURLValidationError("Редиректы audio_url запрещены")
                if not 200 <= response.status_code < 300:
                    raise AudioURLValidationError(
                        f"audio_url вернул HTTP {response.status_code}"
                    )

                content_type = response.headers.get(
                    "content-type", ""
                ).lower().split(";")[0].strip()
                if content_type and not content_type.startswith(
                    _ALLOWED_CONTENT_TYPES
                ):
                    raise AudioURLValidationError(
                        f"Неподдерживаемый Content-Type: {content_type}"
                    )

                with tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=suffix,
                ) as handle:
                    target = Path(handle.name)
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise AudioTooLargeError(
                                f"Аудиофайл больше "
                                f"{max_bytes // (1024 * 1024)} МБ"
                            )
                        handle.write(chunk)

        if target is None or target.stat().st_size <= 0:
            raise AudioURLValidationError("audio_url вернул пустой файл")

        return DownloadedAudio(
            path=target,
            filename=Path(urlparse(url).path).name or target.name,
            content_type=content_type,
            size_bytes=target.stat().st_size,
        )
    except Exception:
        if target is not None:
            target.unlink(missing_ok=True)
        raise
