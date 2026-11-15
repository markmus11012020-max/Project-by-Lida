from __future__ import annotations

from app.security import Anonymizer


def test_masks_name_phone_and_email() -> None:
    text = (
        "Здравствуйте, меня зовут Анна, телефон +7 900 123-45-67, "
        "email anna@example.ru."
    )
    result = Anonymizer().anonymize(text)

    assert "[PERSON_1]" in result.text
    assert "[PHONE_1]" in result.text
    assert "[EMAIL_1]" in result.text
    assert "Анна" not in result.text
    assert "+7 900 123-45-67" not in result.text
    assert "anna@example.ru" not in result.text
    assert result.restore() == text


def test_masks_documents_and_card() -> None:
    text = (
        "Клиент Иван Петров, паспорт 45 06 № 123456, "
        "ИНН 7707083893, СНИЛС 112-233-445 95, "
        "карта 4111 1111 1111 1111."
    )
    result = Anonymizer().anonymize(text)

    assert "[PERSON_1]" in result.text
    assert "[PASSPORT_1]" in result.text
    assert "[INN_1]" in result.text
    assert "[SNILS_1]" in result.text
    assert "[CARD_1]" in result.text
    assert "Иван Петров" not in result.text
    assert "7707083893" not in result.text
    assert "4111 1111 1111 1111" not in result.text


def test_masks_org_and_address() -> None:
    text = (
        "ООО Ромашка, г. Москва, ул. Ленина, д. 10, кв. 5. "
        "Клиент ждёт доставку."
    )
    result = Anonymizer().anonymize(text)

    assert "[ORG_1]" in result.text
    assert "[ADDRESS_1]" in result.text
    assert "[ADDRESS_2]" in result.text
    assert "ООО Ромашка" not in result.text
    assert "ул. Ленина" not in result.text


def test_does_not_mask_order_number() -> None:
    text = "Оплатил заказ №12345, доставки нет."
    result = Anonymizer().anonymize(text)

    assert result.text == text
    assert result.masked_count == 0
    assert result.restore() == text


def test_same_value_gets_same_token() -> None:
    text = "Анна звонила. Анна ждёт ответа."
    result = Anonymizer().anonymize(text)

    assert result.text.count("[PERSON_1]") == 2
    assert result.stats["PERSON"] == 2
    assert result.mapping == {"[PERSON_1]": "Анна"}


def test_restore_only_allowed_kinds() -> None:
    text = "Анна, +7 900 123-45-67, anna@example.ru"
    result = Anonymizer().anonymize(text)

    restored = result.restore(allowed_kinds={"PERSON", "PHONE"})
    assert "Анна" in restored
    assert "+7 900 123-45-67" in restored
    assert "[EMAIL_1]" in restored
    assert "anna@example.ru" not in restored


def test_invalid_card_is_not_masked() -> None:
    text = "Номер 1234 5678 9012 3456 не карта."
    result = Anonymizer().anonymize(text)

    assert "1234 5678 9012 3456" in result.text
    assert "CARD" not in result.stats


def test_disabled_anonymizer_returns_input() -> None:
    text = "Анна, +7 900 123-45-67"
    result = Anonymizer(enabled=False).anonymize(text)

    assert result.text == text
    assert not result.entities
    assert not result.mapping


def test_masking_is_stable() -> None:
    anonymizer = Anonymizer()
    first = anonymizer.anonymize("Анна, +7 900 123-45-67")
    second = anonymizer.anonymize(first.text)

    assert second.text == first.text
    assert second.masked_count == 0
