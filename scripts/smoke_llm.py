"""Minimal live check of the AITUNNEL key and model."""

from __future__ import annotations

import json
import sys

from app.config import get_settings
from app.llm import AITunnelClient


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main() -> int:
    _configure_stdout()
    settings = get_settings()
    key = settings.aitunnel_api_key
    masked = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "(short)"
    print(f"Base URL: {settings.aitunnel_base_url}")
    print(f"Model: {settings.aitunnel_model}")
    print(f"API key: {masked}")
    print(f"Key configured: {settings.llm_configured}")

    if not settings.llm_configured:
        print(
            "\nКлюч не настроен. Вставьте реальный AITUNNEL_API_KEY в .env.",
            file=sys.stderr,
        )
        return 1

    client = AITunnelClient(settings)
    messages = [
        {
            "role": "system",
            "content": (
                "Ты — тестовый модуль. Верни только JSON-объект "
                '{"ok": true, "message": "ready"}.'
            ),
        },
        {"role": "user", "content": "Проверка соединения."},
    ]
    try:
        response = client.complete_json(messages)
    except Exception as exc:
        print(f"\nОшибка: {exc}", file=sys.stderr)
        return 1

    print(f"\nLatency: {response.latency_ms} ms")
    print(f"Usage: {json.dumps(response.usage, ensure_ascii=False)}")
    print("Content:")
    print(response.content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
