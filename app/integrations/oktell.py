"""Oktell call export adapter.

The exact Oktell API version varies between installations. The client keeps
paths and the since-parameter configurable; the default parser accepts a list
or a wrapper with ``items``/``calls``/``data``/``results``. Before connecting
to a real PBX, verify the endpoint and field names against its API docs.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import httpx

from app.audio import AudioTooLargeError, validate_audio_file
from app.audio.download import DownloadedAudio


class OktellError(RuntimeError):
    """Raised when Oktell is unavailable or returns an invalid response."""


@dataclass(frozen=True)
class OktellCall:
    external_id: str
    recording_url: str | None
    started_at: str | None = None
    duration_ms: int = 0
    direction: str | None = None
    operator: str | None = None
    client: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OktellSyncReport:
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class OktellClient:
    def __init__(
        self,
        base_url: str,
        calls_path: str = "/api/v1/calls",
        api_key: str = "",
        username: str = "",
        password: str = "",
        timeout: float = 30.0,
        page_size: int = 100,
        since_param: str = "from",
        recording_allowlist: str = "",
        verify_ssl: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.calls_path = calls_path
        self.api_key = api_key
        self.username = username
        self.password = password
        self.timeout = timeout
        self.page_size = page_size
        self.since_param = since_param
        self.recording_allowlist = recording_allowlist
        self.verify_ssl = verify_ssl
        self.transport = transport

    @classmethod
    def from_settings(cls, settings) -> "OktellClient":
        return cls(
            base_url=settings.oktell_base_url,
            calls_path=settings.oktell_calls_path,
            api_key=settings.oktell_api_key,
            username=settings.oktell_username,
            password=settings.oktell_password,
            timeout=settings.oktell_timeout,
            page_size=settings.oktell_page_size,
            since_param=settings.oktell_since_param,
            recording_allowlist=settings.oktell_recording_allowlist,
            verify_ssl=settings.oktell_verify_ssl,
        )

    def _auth_headers(self) -> dict[str, str]:
        if self.api_key.strip():
            return {"Authorization": f"Bearer {self.api_key.strip()}"}
        if self.username.strip():
            import base64

            raw = f"{self.username}:{self.password}".encode("utf-8")
            token = base64.b64encode(raw).decode("ascii")
            return {"Authorization": f"Basic {token}"}
        return {}

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return self.base_url.rstrip("/") + "/" + path.lstrip("/")

    def list_calls(
        self,
        since: datetime | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[OktellCall]:
        params: dict[str, Any] = {
            "limit": limit or self.page_size,
            "offset": offset,
        }
        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            params[self.since_param] = since.isoformat()

        try:
            with httpx.Client(
                timeout=self.timeout,
                verify=self.verify_ssl,
                transport=self.transport,
            ) as client:
                response = client.get(
                    self._url(self.calls_path),
                    headers=self._auth_headers(),
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise OktellError(
                f"Oktell недоступен: {type(exc).__name__}"
            ) from exc

        if not 200 <= response.status_code < 300:
            raise OktellError(
                f"Oktell вернул HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OktellError("Oktell вернул не JSON") from exc

        items = self._extract_items(payload)
        calls: list[OktellCall] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            external_id = _first(
                item,
                "external_id",
                "call_id",
                "uuid",
                "id",
            )
            if not external_id:
                continue
            recording = _first(
                item,
                "recording_url",
                "record_url",
                "audio_url",
                "url",
            )
            if recording and not str(recording).startswith(
                ("http://", "https://")
            ):
                recording = urljoin(self.base_url, str(recording))
            calls.append(
                OktellCall(
                    external_id=str(external_id),
                    recording_url=str(recording) if recording else None,
                    started_at=_optional_string(
                        _first(item, "started_at", "start_time", "date")
                    ),
                    duration_ms=_duration_ms(item),
                    direction=_optional_string(item.get("direction")),
                    operator=_optional_string(
                        _first(item, "operator", "operator_name", "user")
                    ),
                    client=_optional_string(
                        _first(item, "client", "client_name", "phone")
                    ),
                    raw=item,
                )
            )
        return calls

    @staticmethod
    def _extract_items(payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("items", "calls", "data", "results", "result"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def download_recording(
        self,
        call: OktellCall | str,
        max_bytes: int = 50 * 1024 * 1024,
    ) -> DownloadedAudio:
        url = call.recording_url if isinstance(call, OktellCall) else call
        if not url:
            raise OktellError("У звонка нет recording_url")

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise OktellError("Некорректный recording_url")
        self._check_recording_host(parsed.hostname.lower())

        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {".mp3", ".wav", ".ogg", ".m4a"}:
            suffix = ".bin"

        target: Path | None = None
        try:
            with httpx.Client(
                timeout=self.timeout,
                verify=self.verify_ssl,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                with client.stream(
                    "GET",
                    url,
                    headers=self._auth_headers(),
                ) as response:
                    if 300 <= response.status_code < 400:
                        raise OktellError("Редиректы recording_url запрещены")
                    if not 200 <= response.status_code < 300:
                        raise OktellError(
                            f"Запись вернула HTTP {response.status_code}"
                        )
                    content_type = (
                        response.headers.get("content-type", "")
                        .lower()
                        .split(";")[0]
                        .strip()
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
                                    f"Запись больше "
                                    f"{max_bytes // (1024 * 1024)} МБ"
                                )
                            handle.write(chunk)
            if target is None or target.stat().st_size <= 0:
                raise OktellError("Oktell вернул пустой файл записи")
            return DownloadedAudio(
                path=target,
                filename=Path(parsed.path).name or target.name,
                content_type=content_type,
                size_bytes=target.stat().st_size,
            )
        except Exception:
            if target is not None:
                target.unlink(missing_ok=True)
            raise

    def _check_recording_host(self, host: str) -> None:
        allowed = {
            item.strip().lower()
            for item in self.recording_allowlist.split(",")
            if item.strip()
        }
        if allowed:
            if not any(
                host == item or host.endswith("." + item) for item in allowed
            ):
                raise OktellError("Домен записи не входит в allowlist")
            return
        base_host = (urlparse(self.base_url).hostname or "").lower()
        if base_host and not (
            host == base_host or host.endswith("." + base_host)
        ):
            raise OktellError(
                "Домен записи не совпадает с Oktell; добавьте его в "
                "OKTELL_RECORDING_ALLOWLIST"
            )


class OktellSync:
    def __init__(
        self,
        client: OktellClient,
        store: Any,
        max_bytes: int = 50 * 1024 * 1024,
        title_prefix: str = "Oktell",
    ) -> None:
        self.client = client
        self.store = store
        self.max_bytes = max_bytes
        self.title_prefix = title_prefix

    def run(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> OktellSyncReport:
        calls = self.client.list_calls(since=since, limit=limit)
        imported = skipped = failed = 0
        errors: list[str] = []

        for call in calls:
            if not call.recording_url:
                skipped += 1
                continue
            if self.store.find_by_external_id(call.external_id):
                skipped += 1
                continue

            path: Path | None = None
            try:
                downloaded = self.client.download_recording(
                    call,
                    max_bytes=self.max_bytes,
                )
                path = downloaded.path
                validate_audio_file(
                    path,
                    filename=downloaded.filename,
                    max_bytes=self.max_bytes,
                )
                self.store.ingest_audio(
                    path,
                    filename=downloaded.filename,
                    title=f"{self.title_prefix} {call.external_id}",
                    external_id=call.external_id,
                )
                imported += 1
            except Exception as exc:  # noqa: BLE001 - one bad call must not stop sync
                failed += 1
                errors.append(f"{call.external_id}: {type(exc).__name__}: {exc}")
            finally:
                if path is not None:
                    path.unlink(missing_ok=True)

        return OktellSyncReport(
            imported=imported,
            skipped=skipped,
            failed=failed,
            errors=errors,
        )


def _first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _duration_ms(item: dict[str, Any]) -> int:
    value = item.get("duration_ms")
    if value is not None:
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            pass
    for key in ("duration", "duration_sec", "length"):
        value = item.get(key)
        if value is not None:
            try:
                return max(0, int(float(value) * 1000))
            except (TypeError, ValueError):
                continue
    return 0
