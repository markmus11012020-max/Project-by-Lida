from __future__ import annotations

import wave
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.audio import DownloadedAudio
from app.integrations import (
    OktellCall,
    OktellClient,
    OktellSync,
)


def _wav(path: Path, seconds: float = 0.2) -> Path:
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(8000)
        file.writeframes(b"\x00\x00" * int(8000 * seconds))
    return path


def test_list_calls_parses_and_signs_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "call-1",
                        "recording_url": "https://oktell.example/records/1.mp3",
                        "started_at": "2026-11-15T10:00:00+03:00",
                        "duration": 12.5,
                        "operator": "Анна",
                        "client": "+7 900 000-00-00",
                    }
                ]
            },
        )

    client = OktellClient(
        "https://oktell.example",
        api_key="token",
        transport=httpx.MockTransport(handler),
    )
    calls = client.list_calls(
        since=datetime(2026, 11, 15, tzinfo=timezone.utc),
        limit=10,
    )

    assert captured["auth"] == "Bearer token"
    assert "from=2026-11-15" in str(captured["url"])
    assert "limit=10" in str(captured["url"])
    assert len(calls) == 1
    call = calls[0]
    assert call.external_id == "call-1"
    assert call.duration_ms == 12500
    assert call.operator == "Анна"
    assert call.recording_url == "https://oktell.example/records/1.mp3"


def test_download_recording(tmp_path: Path) -> None:
    source = _wav(tmp_path / "source.wav")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=source.read_bytes(),
            headers={"content-type": "audio/wav"},
        )

    client = OktellClient(
        "https://oktell.example",
        transport=httpx.MockTransport(handler),
    )
    call = OktellCall(
        external_id="call-1",
        recording_url="https://oktell.example/records/1.wav",
    )
    downloaded = client.download_recording(call)

    assert downloaded.size_bytes == source.stat().st_size
    assert downloaded.filename == "1.wav"
    assert downloaded.path.exists()
    downloaded.path.unlink()


def test_download_rejects_foreign_host(tmp_path: Path) -> None:
    client = OktellClient("https://oktell.example")
    call = OktellCall(
        external_id="call-1",
        recording_url="https://evil.example/records/1.wav",
    )

    try:
        client.download_recording(call)
    except Exception as exc:
        assert "OKTELL_RECORDING_ALLOWLIST" in str(exc)
    else:
        raise AssertionError("foreign host must be rejected")


class FakeClient:
    def __init__(self, calls: list[OktellCall], files: dict[str, Path]) -> None:
        self.calls = calls
        self.files = files
        self.downloaded: list[str] = []

    def list_calls(self, since=None, limit=100):
        return self.calls

    def download_recording(self, call: OktellCall, max_bytes: int = 0):
        self.downloaded.append(call.external_id)
        path = self.files[call.external_id]
        return DownloadedAudio(
            path=path,
            filename=path.name,
            content_type="audio/wav",
            size_bytes=path.stat().st_size,
        )


class FakeStore:
    def __init__(self, existing: set[str]) -> None:
        self.existing = existing
        self.imported: list[dict] = []

    def find_by_external_id(self, external_id: str):
        return {"id": "existing"} if external_id in self.existing else None

    def ingest_audio(self, path: Path, filename: str, title: str, external_id: str):
        self.imported.append(
            {
                "filename": filename,
                "title": title,
                "external_id": external_id,
                "path": path,
            }
        )
        return "new"


def test_sync_skips_existing_and_imports_new(tmp_path: Path) -> None:
    first = _wav(tmp_path / "first.wav")
    second = _wav(tmp_path / "second.wav")
    calls = [
        OktellCall("existing", "https://oktell.example/1.wav"),
        OktellCall("new", "https://oktell.example/2.wav"),
        OktellCall("no-recording", None),
    ]
    client = FakeClient(calls, {"new": second})
    store = FakeStore({"existing"})
    report = OktellSync(client, store).run(limit=10)

    assert report.imported == 1
    assert report.skipped == 2
    assert report.failed == 0
    assert store.imported[0]["external_id"] == "new"
    assert store.imported[0]["title"] == "Oktell new"
    assert store.imported[0]["path"] == second
    assert not second.exists()
    assert first.exists()


def test_sync_continues_after_one_failure(tmp_path: Path) -> None:
    good = _wav(tmp_path / "good.wav")
    calls = [
        OktellCall("bad", "https://oktell.example/bad.wav"),
        OktellCall("good", "https://oktell.example/good.wav"),
    ]
    client = FakeClient(calls, {"good": good})
    store = FakeStore(set())

    def download(call, max_bytes=0):
        if call.external_id == "bad":
            raise RuntimeError("download failed")
        return DownloadedAudio(
            path=good,
            filename=good.name,
            content_type="audio/wav",
            size_bytes=good.stat().st_size,
        )

    client.download_recording = download
    report = OktellSync(client, store).run(limit=10)

    assert report.imported == 1
    assert report.failed == 1
    assert report.errors
