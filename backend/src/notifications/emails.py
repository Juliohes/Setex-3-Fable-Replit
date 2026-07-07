"""Stub de emails (MVP). Sin SMTP configurado ⇒ log estructurado, jamás rompe."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from shared.config import get_settings
from shared.logging import get_logger

log = get_logger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        log.info("email.skipped_no_smtp", to=to, subject=subject)
        return
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, 587, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)
