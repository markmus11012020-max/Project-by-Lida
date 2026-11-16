from __future__ import annotations

from app.config import Settings
from app.notifications import send_lead_notification


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host: str, port: int, timeout: float = 0) -> None:
        self.host = host
        self.port = port
        self.login_args = None
        self.message = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def login(self, username: str, password: str) -> None:
        self.login_args = (username, password)

    def send_message(self, message) -> None:
        self.message = message


def _settings(**overrides) -> Settings:
    payload = {
        "_env_file": None,
        "aitunnel_api_key": "sk-test",
        "mail_enabled": True,
        "smtp_host": "smtp.mail.ru",
        "smtp_port": 465,
        "smtp_username": "aillix@mail.ru",
        "smtp_password": "app-password",
        "lead_notify_to": "aillix@mail.ru",
    }
    payload.update(overrides)
    return Settings(**payload)


def test_send_lead_notification(monkeypatch) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr("app.notifications.smtplib.SMTP_SSL", FakeSMTP)

    sent = send_lead_notification(
        _settings(),
        {
            "id": "lead-1",
            "name": "Иван",
            "company": "ООО Тест",
            "contact": "+7 900 000-00-00",
            "volume": "100–500",
            "phone_system": "Oktell",
            "comment": "Нужен пилот",
        },
    )

    assert sent is True
    smtp = FakeSMTP.instances[0]
    assert smtp.login_args == ("aillix@mail.ru", "app-password")
    assert smtp.message["To"] == "aillix@mail.ru"
    assert "Иван" in smtp.message.get_content()
    assert "Oktell" in smtp.message.get_content()


def test_mail_disabled_is_noop() -> None:
    assert send_lead_notification(
        _settings(mail_enabled=False),
        {"name": "Иван"},
    ) is False


def test_incomplete_mail_settings_is_noop() -> None:
    assert send_lead_notification(
        _settings(smtp_password=""),
        {"name": "Иван"},
    ) is False
