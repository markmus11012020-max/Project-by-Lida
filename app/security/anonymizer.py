"""PII anonymization for Russian call transcripts and request texts.

The module is intentionally dependency-free: regexes and a small Russian
name dictionary cover the pilot cases. A NER adapter can be plugged in later
without changing the public API.

Masking is reversible: ``AnonymizationResult.restore()`` returns the original
values for allowed entity kinds. The mapping must never be written to logs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

PIIKind = Literal[
    "PERSON",
    "PHONE",
    "EMAIL",
    "ORG",
    "CARD",
    "ADDRESS",
    "PASSPORT",
    "SNILS",
    "INN",
]

# Common Russian first names and their case forms. Unknown surnames are
# handled separately by the suffix pattern below.
_NAME_FORMS: dict[str, tuple[str, ...]] = {
    "Анна": ("Анна", "Анны", "Анне", "Анну", "Анной"),
    "Мария": ("Мария", "Марии", "Марию", "Марией"),
    "Ольга": ("Ольга", "Ольги", "Ольге", "Ольгу", "Ольгой"),
    "Елена": ("Елена", "Елены", "Елене", "Елену", "Еленой"),
    "Татьяна": ("Татьяна", "Татьяны", "Татьяне", "Татьяну", "Татьяной"),
    "Наталья": ("Наталья", "Натальи", "Наталье", "Наталью", "Натальей"),
    "Ирина": ("Ирина", "Ирины", "Ирине", "Ирину", "Ириной"),
    "Светлана": ("Светлана", "Светланы", "Светлане", "Светлану", "Светланой"),
    "Екатерина": ("Екатерина", "Екатерины", "Екатерине", "Екатерину", "Екатериной"),
    "Ксения": ("Ксения", "Ксении", "Ксению", "Ксенией"),
    "Юлия": ("Юлия", "Юлии", "Юлию", "Юлией"),
    "Дарья": ("Дарья", "Дарьи", "Дарье", "Дарью", "Дарьей"),
    "Виктория": ("Виктория", "Виктории", "Викторию", "Викторией"),
    "Анастасия": ("Анастасия", "Анастасии", "Анастасию", "Анастасией"),
    "Галина": ("Галина", "Галины", "Галине", "Галину", "Галиной"),
    "Людмила": ("Людмила", "Людмилы", "Людмиле", "Людмилу", "Людмилой"),
    "Иван": ("Иван", "Ивана", "Ивану", "Иваном", "Иване"),
    "Петр": ("Петр", "Петра", "Петру", "Петром", "Петре"),
    "Сергей": ("Сергей", "Сергея", "Сергею", "Сергеем", "Сергее"),
    "Алексей": ("Алексей", "Алексея", "Алексею", "Алексеем", "Алексее"),
    "Дмитрий": ("Дмитрий", "Дмитрия", "Дмитрию", "Дмитрием", "Дмитрии"),
    "Александр": ("Александр", "Александра", "Александру", "Александром", "Александре"),
    "Михаил": ("Михаил", "Михаила", "Михаилу", "Михаилом", "Михаиле"),
    "Андрей": ("Андрей", "Андрея", "Андрею", "Андреем", "Андрее"),
    "Роман": ("Роман", "Романа", "Роману", "Романом", "Романе"),
    "Павел": ("Павел", "Павла", "Павлу", "Павлом", "Павле"),
    "Владимир": ("Владимир", "Владимира", "Владимиру", "Владимиром", "Владимире"),
    "Николай": ("Николай", "Николая", "Николаю", "Николаем", "Николае"),
    "Максим": ("Максим", "Максима", "Максиму", "Максимом", "Максиме"),
    "Артем": ("Артем", "Артема", "Артему", "Артемом", "Артеме"),
    "Евгений": ("Евгений", "Евгения", "Евгению", "Евгением", "Евгении"),
}

_NAME_FORM_RE = re.compile(
    r"(?<![\w-])(?:"
    + "|".join(
        re.escape(form)
        for form in sorted(
            {form for forms in _NAME_FORMS.values() for form in forms},
            key=len,
            reverse=True,
        )
    )
    + r")(?![\w-])"
)

_PATTERNS: tuple[tuple[PIIKind, re.Pattern[str], int], ...] = (
    (
        "EMAIL",
        re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9-])"),
        90,
    ),
    (
        "PHONE",
        re.compile(
            r"(?<![\d+])(?:\+7|8)[\s\-\(]*\d{3}[\s\-\)]*"
            r"\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)"
        ),
        80,
    ),
    (
        "CARD",
        re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)"),
        75,
    ),
    (
        "SNILS",
        re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}[\s]?\d{2}(?!\d)"),
        70,
    ),
    (
        "PASSPORT",
        re.compile(
            r"(?i)\bпаспорт[а-яё\s:№-]*\d{2}\s?\d{2}\s?№?\s?\d{6}\b"
        ),
        70,
    ),
    (
        "INN",
        re.compile(r"(?i)\bИНН\s*[:№-]?\s*\d{10}(?:\d{2})?\b"),
        70,
    ),
    (
        "ORG",
        re.compile(
            r"(?<![\w-])(?:ООО|ОАО|ЗАО|ПАО|АО|ИП|НКО|ГК)\s+"
            r"(?:[«\"'][^»\"'\n]{2,60}[»\"']|"
            r"[А-ЯЁA-Z0-9][\w-]*(?:\s+[А-ЯЁA-Z0-9][\w-]*)?)"
        ),
        60,
    ),
    (
        "ADDRESS",
        re.compile(
            r"(?<![\w-])(?:г\.|город|ул\.|улица|пр-т|проспект|пер\.|переулок|"
            r"ш\.|шоссе|наб\.|набережная|д\.|дом|кв\.|квартира|оф\.|офис)"
            r"\s*[А-ЯЁа-яёA-Za-z0-9][^,;.\n]{0,60}"
        ),
        55,
    ),
    (
        "PERSON",
        re.compile(
            r"(?<![\w-])[А-ЯЁ][а-яё]*(?:ович|евич|ич|овна|евна|ична|инична)"
            r"(?![\w-])"
        ),
        50,
    ),
    (
        "PERSON",
        re.compile(
            r"(?<![\w-])[А-ЯЁ][а-яё]*(?:ов|ев|ёв|ин|ын|ский|цкий|ской|цкой|"
            r"ова|ева|ёва|ина|ына|ская|цкая)(?![\w-])"
        ),
        45,
    ),
    (
        "PERSON",
        re.compile(r"(?<![\w-])[А-ЯЁ]\.\s?[А-ЯЁ]\.(?![\w-])"),
        44,
    ),
)


@dataclass(frozen=True)
class PIIEntity:
    kind: PIIKind
    value: str
    start: int
    end: int
    token: str


@dataclass
class AnonymizationResult:
    text: str
    entities: list[PIIEntity] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)
    kinds: dict[str, PIIKind] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def masked_count(self) -> int:
        return len(self.entities)

    @property
    def has_pii(self) -> bool:
        return bool(self.entities)

    def restore(
        self,
        text: str | None = None,
        allowed_kinds: Iterable[str] | None = None,
    ) -> str:
        """Return values only for the allowed entity kinds.

        By default all kinds are restored. Pass ``allowed_kinds={'PERSON',
        'PHONE'}`` for the narrow CRM card case from the technical spec.
        """

        source = self.text if text is None else text
        allowed = (
            {kind.upper() for kind in allowed_kinds}
            if allowed_kinds is not None
            else None
        )
        for token, value in self.mapping.items():
            if allowed is not None and self.kinds[token] not in allowed:
                continue
            source = source.replace(token, value)
        return source


def _luhn(number: str) -> bool:
    digits = [int(char) for char in number if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


@dataclass(frozen=True)
class _Candidate:
    kind: PIIKind
    value: str
    start: int
    end: int
    priority: int

    @property
    def length(self) -> int:
        return self.end - self.start


def _overlaps(left: _Candidate, right: _Candidate) -> bool:
    return left.start < right.end and right.start < left.end


class Anonymizer:
    """Regex-based reversible masking of Russian PII."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def anonymize(self, text: str) -> AnonymizationResult:
        if not text or not self.enabled:
            return AnonymizationResult(text=text)

        candidates: list[_Candidate] = []
        for kind, pattern, priority in _PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0).strip()
                if not value:
                    continue
                start = match.start()
                end = start + len(value)
                if kind == "CARD" and not _luhn(value):
                    continue
                if kind == "ADDRESS":
                    value = value.rstrip(" \t.,;:-")
                    end = start + len(value)
                    if len(value) < 4:
                        continue
                candidates.append(
                    _Candidate(
                        kind=kind,
                        value=value,
                        start=start,
                        end=end,
                        priority=priority,
                    )
                )

        # Known first names are separate candidates so that "Иван Петров"
        # can be merged into one PERSON span below.
        for match in _NAME_FORM_RE.finditer(text):
            candidates.append(
                _Candidate(
                    kind="PERSON",
                    value=match.group(0),
                    start=match.start(),
                    end=match.end(),
                    priority=50,
                )
            )

        # Prefer high-priority and longer spans; skip overlaps.
        selected: list[_Candidate] = []
        for candidate in sorted(
            candidates,
            key=lambda item: (-item.priority, -item.length, item.start),
        ):
            if not any(_overlaps(candidate, other) for other in selected):
                selected.append(candidate)
        selected.sort(key=lambda item: item.start)

        # Merge adjacent PERSON spans ("Иван" + "Петров").
        merged: list[_Candidate] = []
        for candidate in selected:
            if (
                merged
                and candidate.kind == "PERSON"
                and merged[-1].kind == "PERSON"
                and candidate.start >= merged[-1].end
                and text[merged[-1].end : candidate.start].strip() == ""
                and candidate.start - merged[-1].end <= 2
            ):
                previous = merged[-1]
                merged[-1] = _Candidate(
                    kind="PERSON",
                    value=text[previous.start : candidate.end],
                    start=previous.start,
                    end=candidate.end,
                    priority=previous.priority,
                )
            else:
                merged.append(candidate)

        counters: dict[str, int] = {}
        token_by_key: dict[tuple[str, str], str] = {}
        entities: list[PIIEntity] = []
        mapping: dict[str, str] = {}
        kinds: dict[str, PIIKind] = {}

        for candidate in merged:
            key = (candidate.kind, candidate.value)
            token = token_by_key.get(key)
            if token is None:
                counters[candidate.kind] = counters.get(candidate.kind, 0) + 1
                token = f"[{candidate.kind}_{counters[candidate.kind]}]"
                token_by_key[key] = token
                mapping[token] = candidate.value
                kinds[token] = candidate.kind
            entities.append(
                PIIEntity(
                    kind=candidate.kind,
                    value=candidate.value,
                    start=candidate.start,
                    end=candidate.end,
                    token=token,
                )
            )

        chunks: list[str] = []
        cursor = len(text)
        for entity in reversed(entities):
            chunks.append(text[entity.end : cursor])
            chunks.append(entity.token)
            cursor = entity.start
        chunks.append(text[:cursor])
        masked_text = "".join(reversed(chunks))

        stats: dict[str, int] = {}
        for entity in entities:
            stats[entity.kind] = stats.get(entity.kind, 0) + 1

        return AnonymizationResult(
            text=masked_text,
            entities=entities,
            mapping=mapping,
            kinds=kinds,
            stats=stats,
        )

    def mask(self, text: str) -> str:
        return self.anonymize(text).text
