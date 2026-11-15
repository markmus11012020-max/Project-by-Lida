from __future__ import annotations

import socket
from pathlib import Path

import httpx
import pytest

from app.audio import (
    AudioTooLargeError,
    AudioURLValidationError,
    download_audio_url,
    validate_audio_url,
)


def _public_resolver(host: str, port: int, **kwargs):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            ("93.184.216.34", port),
        )
    ]


def _private_resolver(host: str, port: int, **kwargs):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            ("127.0.0.1", port),
        )
    ]


def _wav_bytes() -> bytes:
    return b"RIFF" + b"\x00" * 100


def test_url_requires_https() -> None:
    with pytest.raises(AudioURLValidationError):
        validate_audio_url("http://example.com/call.wav")


def test_url_rejects_private_ip() -> None:
    with pytest.raises(AudioURLValidationError):
        validate_audio_url(
            "https://example.com/call.wav",
            resolver=_private_resolver,
        )


def test_url_allowlist() -> None:
    with pytest.raises(AudioURLValidationError):
        validate_audio_url(
            "https://evil.example/call.wav",
            allowlist="crm.example",
            resolver=_public_resolver,
        )

    assert validate_audio_url(
        "https://crm.example/call.wav",
        allowlist="crm.example",
        resolver=_public_resolver,
    )


def test_url_rejects_credentials_and_ports() -> None:
    with pytest.raises(AudioURLValidationError):
        validate_audio_url(
            "https://user:pass@example.com/call.wav",
            resolver=_public_resolver,
        )
    with pytest.raises(AudioURLValidationError):
        validate_audio_url(
            "https://example.com:8443/call.wav",
            resolver=_public_resolver,
        )


def test_download_success(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_wav_bytes(),
            headers={"content-type": "audio/wav"},
        )

    downloaded = download_audio_url(
        "https://example.com/call.wav",
        max_bytes=1024,
        transport=httpx.MockTransport(handler),
        resolver=_public_resolver,
    )

    assert downloaded.filename == "call.wav"
    assert downloaded.content_type == "audio/wav"
    assert downloaded.size_bytes == len(_wav_bytes())
    assert downloaded.path.exists()
    downloaded.path.unlink()


def test_download_rejects_large_file() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"x" * 100,
            headers={"content-type": "audio/wav"},
        )

    with pytest.raises(AudioTooLargeError):
        download_audio_url(
            "https://example.com/call.wav",
            max_bytes=10,
            transport=httpx.MockTransport(handler),
            resolver=_public_resolver,
        )


def test_download_rejects_content_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>", headers={"content-type": "text/html"})

    with pytest.raises(AudioURLValidationError):
        download_audio_url(
            "https://example.com/call.wav",
            max_bytes=1024,
            transport=httpx.MockTransport(handler),
            resolver=_public_resolver,
        )


def test_download_rejects_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example"})

    with pytest.raises(AudioURLValidationError):
        download_audio_url(
            "https://example.com/call.wav",
            max_bytes=1024,
            transport=httpx.MockTransport(handler),
            resolver=_public_resolver,
        )
