"""Napkin economics: manual vs automated processing time and LLM cost."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from app.pricing import cost_from_usage


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(description="Мини-экономика проекта")
    parser.add_argument(
        "--db",
        default="data/test_run.db",
        help="Путь к SQLite с прогоном",
    )
    parser.add_argument(
        "--manual-minutes",
        type=float,
        default=6.0,
        help="Минут на одно обращение вручную",
    )
    parser.add_argument(
        "--processed-minutes",
        type=float,
        default=0.5,
        help="Минут проверки одного автоматически обработанного кейса",
    )
    parser.add_argument(
        "--escalated-minutes",
        type=float,
        default=5.0,
        help="Минут на один эскалированный кейс",
    )
    parser.add_argument(
        "--output",
        default="docs/economics.txt",
        help="Куда сохранить отчёт",
    )
    args = parser.parse_args(argv)

    path = Path(args.db)
    if not path.exists():
        print(f"База не найдена: {path}. Сначала запустите batch-прогон.")
        return 1

    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT scenario, status, latency_ms, model, usage_json "
        "FROM processing_log ORDER BY created_at"
    ).fetchall()
    connection.close()

    if not rows:
        print("В базе нет записей.")
        return 1

    total = len(rows)
    statuses = Counter(row["status"] for row in rows)
    scenarios = Counter(row["scenario"] for row in rows)
    processed = statuses.get("processed", 0)
    human = total - processed

    total_cost = 0.0
    total_latency = 0
    for row in rows:
        usage = json.loads(row["usage_json"] or "{}")
        total_cost += cost_from_usage(usage, row["model"] or "")
        total_latency += int(row["latency_ms"] or 0)

    manual_minutes = total * args.manual_minutes
    automated_minutes = (
        processed * args.processed_minutes + human * args.escalated_minutes
    )
    saved_minutes = manual_minutes - automated_minutes
    saved_percent = (
        saved_minutes / manual_minutes * 100 if manual_minutes else 0.0
    )
    cost_per_100 = total_cost / total * 100 if total else 0.0

    lines = [
        "МИНИ-ЭКОНОМИКА ПРОЕКТА",
        "",
        f"Записей в прогоне: {total}",
        f"По сценариям: {dict(scenarios)}",
        f"По статусам: {dict(statuses)}",
        f"Средняя задержка: {total_latency / total:.0f} мс",
        f"Суммарная стоимость LLM: {total_cost:.4f} ₽",
        f"Стоимость 100 обработок: {cost_per_100:.4f} ₽",
        "",
        "ДОПУЩЕНИЯ",
        f"Ручная обработка одного кейса: {args.manual_minutes:.1f} мин",
        f"Проверка автоматического кейса: {args.processed_minutes:.1f} мин",
        f"Ручная обработка эскалированного кейса: {args.escalated_minutes:.1f} мин",
        "",
        "РАСЧЁТ",
        f"Вручную: {manual_minutes:.1f} мин",
        f"С автоматизацией: {automated_minutes:.1f} мин",
        f"Экономия времени: {saved_minutes:.1f} мин ({saved_percent:.1f}%)",
        f"Уровень автоматизации: {processed / total * 100:.1f}%",
        "",
        "ВЫВОД",
        (
            "Основная ценность — не стоимость LLM, а сокращение ручных минут "
            f"и повышение прозрачности. На выборке из {total} кейсов экономия "
            f"составляет {saved_minutes:.1f} мин."
        ),
    ]

    text = "\n".join(lines) + "\n"
    print(text)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"Сохранено: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
