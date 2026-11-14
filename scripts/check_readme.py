"""Fail if README.md contains common markdown formatting.

The course requires a plain-text README. We still keep the .md extension
because GitHub renders it, but the content must not rely on markdown.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CHECKS: list[tuple[str, re.Pattern[str]]] = [
    ("markdown-заголовок", re.compile(r"^\s{0,3}#{1,6}\s")),
    ("markdown-список", re.compile(r"^\s*[-*+]\s+")),
    ("markdown-цитата", re.compile(r"^\s*>")),
    ("markdown-таблица", re.compile(r"^\s*\|")),
    ("markdown-разделитель таблицы", re.compile(r"\|\s*:?-{3,}")),
    ("markdown-ссылка или картинка", re.compile(r"!?\[[^\]]*\]\([^)]+\)")),
    ("markdown-код", re.compile(r"`")),
    ("markdown-жирный", re.compile(r"\*\*.+?\*\*")),
    ("markdown-жирный", re.compile(r"(?<!_)__.+?__(?!_)")),
    ("markdown-горизонтальная линия", re.compile(r"^\s*([-*_])\1{2,}\s*$")),
]


def check_text(text: str) -> list[tuple[int, str, str]]:
    violations: list[tuple[int, str, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in CHECKS:
            if pattern.search(line):
                violations.append((number, rule, line.strip()))
                break
    return violations


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(description="Проверить README на markdown")
    parser.add_argument(
        "path",
        nargs="?",
        default="README.md",
        help="Путь к README (по умолчанию README.md)",
    )
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(f"Файл не найден: {path}", file=sys.stderr)
        return 1

    text = path.read_text(encoding="utf-8")
    violations = check_text(text)
    if not violations:
        print(f"README OK: markdown-разметка не найдена ({path})")
        return 0

    print(f"README содержит markdown-разметку: {path}", file=sys.stderr)
    for number, rule, line in violations:
        preview = line[:120]
        print(f"  строка {number}: {rule}: {preview}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
