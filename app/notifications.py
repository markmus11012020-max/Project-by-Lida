"""Lead notifications by email."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any

logger = logging.getLogger(__name__)


def send_lead_notification(settings, lead: dict[str, Any]) -> bool:
    if not settings.mail_enabled:
        return False
    if not (
        settings.smtp_host
        and settings.smtp_username
        and settings.smtp_password
        and settings.lead_notify_to
    ):
        logger.warning("Mail is enabled but SMTP settings are incomplete")
        return False

    sender = settings.smtp_from or settings.smtp_username
    subject = (
        "Call-Pilot: заявка с сайта — "
        f"{lead.get('name', '')} / {lead.get('contact', '')}"
    )
    body = "\n".join(
        [
            "Новая заявка с лендинга Call-Pilot",
            "",
            f"Имя: {lead.get('name', '')}",
            f"Компания: {lead.get('company', '')}",
            f"Контакт: {lead.get('contact', '')}",
            f"Объём звонков: {lead.get('volume', '')}",
            f"Телефония / CRM: {lead.get('phone_system', '')}",
            f"Комментарий: {lead.get('comment', '')}",
            f"ID заявки: {lead.get('id', '')}",
        ]
    )

    message = EmailMessage()
    message["From"] = sender
    message["To"] = settings.lead_notify_to
    message["Subject"] = subject
    message.set_content(body)

    try:
        if settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout,
            ) as smtp:
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout,
            ) as smtp:
                smtp.ehlo()
                if settings.smtp_starttls:
                    smtp.starttls()
                    smtp.ehlo()
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
    except Exception:  # noqa: BLE001 - lead is already saved
        logger.exception("Failed to send lead notification")
        return False
    return True
