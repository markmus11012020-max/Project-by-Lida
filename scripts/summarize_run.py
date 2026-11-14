"""Turn data/test_run.json into a readable Markdown summary."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _build_summary(
    rows: list[dict[str, Any]],
    model_override: str = "",
) -> str:
    total = len(rows)
    statuses = Counter(row["actual_status"] for row in rows)
    scenarios: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        scenarios[row["scenario"]][row["actual_status"]] += 1

    valid = sum(1 for row in rows if row.get("valid"))
    mismatches = [row for row in rows if not row.get("status_ok", True)]
    invalid = [
        row
        for row in rows
        if row["actual_status"] in {"invalid", "error"}
    ]
    total_cost = sum(float(row.get("cost_rub") or 0) for row in rows)
    avg_latency = (
        sum(int(row.get("latency_ms") or 0) for row in rows) / total
        if total
        else 0
    )
    automation = statuses.get("processed", 0) / total * 100 if total else 0
    model = model_override or next(
        (row.get("model") for row in rows if row.get("model")),
        "не указана",
    )

    lines = [
        "# Результаты live-прогона",
        "",
        f"Модель: {model}",
        f"Всего кейсов: {total}",
        f"Валидный бизнес-результат: {valid}",
        f"Обработано автоматически: {statuses.get('processed', 0)}",
        f"Эскалировано: {statuses.get('escalated', 0)}",
        f"Невалидный JSON: {statuses.get('invalid', 0)}",
        f"Ошибок LLM/API: {statuses.get('error', 0)}",
        f"Совпадение с ожидаемым статусом: {total - len(mismatches)}/{total}",
        f"Средняя задержка: {avg_latency:.0f} мс",
        f"Суммарная стоимость: {total_cost:.4f} ₽",
        f"Уровень автоматизации: {automation:.1f}%",
        "",
        "## Разбивка по сценариям",
        "",
        "| Сценарий | Кейсов | processed | escalated | invalid | error |",
        "|---|---|---|---|---|---|",
    ]

    for scenario in ("support", "sales", "documents"):
        counts = scenarios.get(scenario, Counter())
        lines.append(
            f"| {scenario} | {sum(counts.values())} | "
            f"{counts.get('processed', 0)} | {counts.get('escalated', 0)} | "
            f"{counts.get('invalid', 0)} | {counts.get('error', 0)} |"
        )

    lines.extend(
        [
            "",
            "## Кейсы",
            "",
            "| Кейс | Ожидание | Факт | OK | Confidence | Причина |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['case_id']} | {row.get('expected_status') or '-'} | "
            f"{row['actual_status']} | "
            f"{'да' if row.get('status_ok') else 'нет'} | "
            f"{row.get('confidence') or '-'} | "
            f"{row.get('escalate_reason') or '-'} |"
        )

    lines.extend(["", "## Выводы", ""])
    if invalid:
        lines.append("Кейсы с invalid/error:")
        for row in invalid:
            lines.append(
                f"- {row['case_id']}: {row['actual_status']} — "
                f"{row.get('error') or 'без ошибки'}"
            )
        lines.append("")
    if mismatches:
        lines.append("Расхождения с ожидаемым статусом:")
        for row in mismatches:
            lines.append(
                f"- {row['case_id']}: ожидалось {row.get('expected_status')}, "
                f"получено {row['actual_status']}"
            )
        lines.append("")
    if not invalid and not mismatches:
        lines.append(
            "Все кейсы дали валидный бизнес-результат и совпали с ожидаемым "
            "статусом. Промпты и правила эскалации работают стабильно."
        )
    else:
        lines.append(
            "Есть отклонения. Проверьте промпты, полноту тестовых входов и "
            "пороги эскалации; изменения фиксируйте в отчёте."
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(description="Сводка live-прогона")
    parser.add_argument(
        "--input",
        default="data/test_run.json",
        help="JSON с результатами batch",
    )
    parser.add_argument(
        "--output",
        default="docs/test_run_summary.md",
        help="Куда сохранить Markdown",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Модель для отчёта, если её нет в JSON",
    )
    args = parser.parse_args(argv)

    source = Path(args.input)
    if not source.exists():
        print(f"Файл не найден: {source}. Сначала запустите batch.")
        return 1

    rows = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        print("В файле нет результатов.")
        return 1

    text = _build_summary(rows, model_override=args.model)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(text)
    print(f"Сохранено: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
