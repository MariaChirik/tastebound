import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger("notification.mailer")
SUBJECT = "Tastebound: оновлення замовлення"


class SmtpMailer:
    def __init__(self, host, port=25, sender="noreply@tastebound.local", username="",
                 password="", starttls=False, timeout=10):
        self.host, self.port, self.sender = host, int(port), sender
        self.username, self.password = username, password
        self.starttls, self.timeout = starttls, timeout

    def send(self, to, text):
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = SUBJECT
        message.set_content(f"{text}\n\nTastebound")
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
            if self.starttls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)


class LogMailer:

    def send(self, to, text):
        log.info("email to %s: %s", to, text)


def default_mailer():
    host = os.environ.get("SMTP_HOST")
    if not host:
        return LogMailer()
    return SmtpMailer(
        host,
        port=os.environ.get("SMTP_PORT", "25"),
        sender=os.environ.get("SMTP_FROM", "noreply@tastebound.local"),
        username=os.environ.get("SMTP_USER", ""),
        password=os.environ.get("SMTP_PASSWORD", ""),
        starttls=os.environ.get("SMTP_STARTTLS", "false").lower() == "true",
    )
