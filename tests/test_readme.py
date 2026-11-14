from __future__ import annotations

from pathlib import Path

from scripts.check_readme import check_text


def test_readme_has_no_markdown() -> None:
    path = Path(__file__).resolve().parent.parent / "README.md"
    assert path.exists(), "README.md отсутствует"
    text = path.read_text(encoding="utf-8")
    violations = check_text(text)
    assert not violations, f"Найдена markdown-разметка: {violations}"
