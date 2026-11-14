"""Command-line interface for single and batch processing."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from app.config import BASE_DIR, Settings, get_settings
from app.db import Database
from app.llm import AITunnelClient
from app.pricing import cost_from_usage
from app.scenarios.registry import SCENARIOS
from app.schemas import EvalCase, ProcessStatus, ScenarioKey
from app.service import ProcessService


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def build_service(
    settings: Settings | None = None,
    db_path: Path | None = None,
) -> ProcessService:
    settings = settings or get_settings()
    db = Database(db_path or settings.database_path)
    db.init()
    return ProcessService(
        settings=settings,
        db=db,
        llm=AITunnelClient(settings),
        scenarios=SCENARIOS,
    )


def _read_text(args: argparse.Namespace) -> str:
    if args.text and args.file:
        raise SystemExit("Укажите только один источник: --text или --file")
    if args.text:
        return args.text
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    raise SystemExit("Нужен --text или --file")


def cmd_ingest(args: argparse.Namespace) -> int:
    service = build_service(db_path=args.db)
    text = _read_text(args)
    response = service.process(
        scenario_key=ScenarioKey(args.scenario),
        text=text,
        source="cli",
    )
    print(response.model_dump_json(indent=2))
    return 0 if response.status in {
        ProcessStatus.PROCESSED,
        ProcessStatus.ESCALATED,
    } else 1


def _reset_test_db(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()


def _read_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"Ошибка JSONL в {path}, строка {line_number}: {exc}"
            ) from exc
        try:
            cases.append(EvalCase.model_validate(payload))
        except Exception as exc:
            raise SystemExit(
                f"Ошибка кейса в {path}, строка {line_number}: {exc}"
            ) from exc
    if not cases:
        raise SystemExit(f"В {path} нет тестовых кейсов")
    return cases


def cmd_batch(args: argparse.Namespace) -> int:
    cases = _read_cases(Path(args.file))
    if args.limit:
        cases = cases[: args.limit]

    db_path = Path(args.db)
    if not args.keep_db:
        _reset_test_db(db_path)
    service = build_service(db_path=db_path)

    rows: list[dict[str, Any]] = []
    invalid = 0
    mismatches = 0
    total_cost = 0.0
    total_latency = 0

    for index, case in enumerate(cases, start=1):
        response = service.process(
            scenario_key=case.scenario,
            text=case.text,
            source="test",
            metadata={"case_id": case.id},
        )
        actual = response.status.value
        expected = (
            case.expected_status.value if case.expected_status else None
        )
        status_ok = expected is None or expected == actual
        valid = response.status in {
            ProcessStatus.PROCESSED,
            ProcessStatus.ESCALATED,
        }
        if not valid:
            invalid += 1
        if not status_ok:
            mismatches += 1

        usage = response.meta.usage or {}
        cost = cost_from_usage(usage, response.meta.model)
        total_cost += cost
        total_latency += response.meta.latency_ms

        result = response.result
        rows.append(
            {
                "case_id": case.id,
                "scenario": case.scenario.value,
                "expected_status": expected,
                "actual_status": actual,
                "status_ok": status_ok,
                "valid": valid,
                "category": result.get("category"),
                "priority": result.get("priority"),
                "confidence": result.get("confidence"),
                "escalate": result.get("escalate"),
                "escalate_reason": result.get("escalate_reason"),
                "summary": result.get("summary"),
                "next_action": result.get("next_action"),
                "score": result.get("score"),
                "latency_ms": response.meta.latency_ms,
                "cost_rub": cost,
                "error": response.error,
                "request_id": response.request_id,
                "note": case.note,
            }
        )
        marker = "OK" if valid and status_ok else "FAIL"
        print(
            f"[{index:02d}/{len(cases)}] {case.id:<22} "
            f"{actual:<10} {marker}"
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    csv_path = Path(args.csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    processed = sum(1 for row in rows if row["actual_status"] == "processed")
    escalated = sum(1 for row in rows if row["actual_status"] == "escalated")
    errors = sum(1 for row in rows if row["actual_status"] == "error")
    invalid_json = sum(1 for row in rows if row["actual_status"] == "invalid")

    print()
    print("ИТОГИ ПРОГОНА")
    print(f"Всего кейсов: {len(rows)}")
    print(f"Валидный бизнес-результат: {len(rows) - invalid}")
    print(f"Обработано автоматически: {processed}")
    print(f"Эскалировано: {escalated}")
    print(f"Невалидный JSON: {invalid_json}")
    print(f"Ошибок LLM/API: {errors}")
    print(f"Совпадение с ожидаемым статусом: {len(rows) - mismatches}/{len(rows)}")
    print(f"Средняя задержка: {total_latency / len(rows):.0f} мс")
    print(f"Суммарная стоимость: {total_cost:.4f} ₽")
    print(f"JSON: {output}")
    print(f"CSV:  {csv_path}")

    if invalid:
        print("\nЕсть невалидные кейсы или ошибки LLM.", file=sys.stderr)
        return 1
    if args.strict and mismatches:
        print(
            "\nСтрогий режим: есть расхождения с ожидаемым статусом.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    service = build_service(db_path=args.db)
    print(json.dumps(service.stats(), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LLM process automation MVP: поддержка, продажи, документы"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Обработать один вход")
    ingest.add_argument(
        "--scenario",
        required=True,
        choices=[key.value for key in ScenarioKey],
    )
    ingest.add_argument("--text", help="Текст входа")
    ingest.add_argument("--file", help="Файл с текстом входа (UTF-8)")
    ingest.add_argument(
        "--db",
        default=str(BASE_DIR / "data" / "app.db"),
        help="Путь к SQLite",
    )
    ingest.set_defaults(func=cmd_ingest)

    batch = subparsers.add_parser("batch", help="Прогнать JSONL с кейсами")
    batch.add_argument(
        "--file",
        default=str(BASE_DIR / "data" / "test_cases.jsonl"),
        help="JSONL с тестовыми кейсами",
    )
    batch.add_argument(
        "--db",
        default=str(BASE_DIR / "data" / "test_run.db"),
        help="Путь к SQLite для прогона",
    )
    batch.add_argument(
        "--output",
        default=str(BASE_DIR / "data" / "test_run.json"),
        help="JSON с результатами",
    )
    batch.add_argument(
        "--csv",
        default=str(BASE_DIR / "data" / "test_run.csv"),
        help="CSV с результатами",
    )
    batch.add_argument("--limit", type=int, default=0, help="Ограничить число кейсов")
    batch.add_argument("--keep-db", action="store_true", help="Не очищать тестовую БД")
    batch.add_argument("--strict", action="store_true", help="Падать при расхождении статусов")
    batch.set_defaults(func=cmd_batch)

    stats = subparsers.add_parser("stats", help="Показать статистику")
    stats.add_argument(
        "--db",
        default=str(BASE_DIR / "data" / "app.db"),
        help="Путь к SQLite",
    )
    stats.set_defaults(func=cmd_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
