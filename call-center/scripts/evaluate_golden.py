"""Evaluate a golden set with the live LLM pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CALL_CENTER_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CALL_CENTER_DIR))

from app.cli import build_service  # noqa: E402
from app.golden import load_cases, run_golden_set  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Golden-set QA evaluation")
    parser.add_argument(
        "--file",
        default=str(CALL_CENTER_DIR / "data" / "golden_set.jsonl"),
    )
    parser.add_argument("--output", default="")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    cases = load_cases(Path(args.file))
    if args.limit:
        cases = cases[: args.limit]
    service = build_service()
    report = run_golden_set(service, cases)
    payload = report.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
