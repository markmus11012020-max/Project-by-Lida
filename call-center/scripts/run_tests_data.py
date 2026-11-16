"""Run Call-Pilot test inputs through the JSON API.

Start the app first:
    call-center\\start.bat
Then:
    .venv\\Scripts\\python.exe call-center\\scripts\\run_tests_data.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "tests_data" / "inputs.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "tests_data" / "last_run.json"


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main() -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(
        description="Прогнать tests_data/inputs.jsonl через API Call-Pilot"
    )
    parser.add_argument("--file", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--base-url", default="http://127.0.0.1:8020")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    path = Path(args.file)
    cases = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not cases:
        print(f"Нет кейсов в {path}")
        return 2

    results: list[dict] = []
    with httpx.Client(base_url=args.base_url, timeout=120) as client:
        for case in cases:
            created = client.post(
                "/api/v1/calls",
                json={
                    "title": case["title"],
                    "transcript": case["transcript"],
                    "client": case.get("client", "Клиент"),
                    "operator": case.get("operator", "Оператор"),
                },
            )
            if created.status_code != 201:
                print(
                    f"{case['id']}: не удалось создать звонок "
                    f"({created.status_code}): {created.text}"
                )
                return 2
            call_id = created.json()["call_id"]

            processed = client.post(f"/api/v1/calls/{call_id}/process")
            if processed.status_code != 200:
                print(
                    f"{case['id']}: ошибка обработки "
                    f"({processed.status_code}): {processed.text}"
                )
                return 2

            detail = client.get(f"/api/v1/calls/{call_id}").json()
            actual = bool(detail.get("need_review"))
            expected_raw = case.get("expected_need_review")
            asserted = expected_raw is not None
            matched = (not asserted) or actual == bool(expected_raw)
            results.append(
                {
                    "id": case["id"],
                    "call_id": call_id,
                    "title": case["title"],
                    "expected_need_review": expected_raw,
                    "asserted": asserted,
                    "actual_need_review": actual,
                    "review_reason": detail.get("review_reason") or "",
                    "qa_score": detail.get("qa_score"),
                    "auto_qa_status": detail.get("auto_qa_status"),
                    "matched": matched,
                }
            )
            mark = "OK" if matched else "MISMATCH"
            expected_text = (
                str(bool(expected_raw)) if asserted else "n/a"
            )
            print(
                f"{case['id']}: expected={expected_text} actual={actual} "
                f"qa={detail.get('qa_score')} reason={detail.get('review_reason')} [{mark}]"
            )

    asserted = [item for item in results if item["asserted"]]
    output = {
        "base_url": args.base_url,
        "total": len(results),
        "asserted": len(asserted),
        "asserted_matched": sum(1 for item in asserted if item["matched"]),
        "informational": len(results) - len(asserted),
        "need_review_expected": sum(
            1 for item in asserted if item["expected_need_review"]
        ),
        "need_review_actual": sum(
            1 for item in results if item["actual_need_review"]
        ),
        "cases": results,
    }
    Path(args.output).write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"\nИтого: asserted {output['asserted_matched']}/{output['asserted']}; "
        f"informational {output['informational']}; "
        f"need_review ожидалось {output['need_review_expected']}, "
        f"получено {output['need_review_actual']}."
    )
    print(f"Отчёт: {args.output}")
    if args.strict and output["asserted_matched"] != output["asserted"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
