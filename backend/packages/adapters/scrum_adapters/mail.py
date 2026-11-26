"""Outbound mail. Open-source default: plain SMTP (Mailpit locally, Postfix/any relay in production)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Protocol

import aiosmtplib


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime: str = "application/octet-stream"


@dataclass
class OutboundMail:
    to: list[str]
    subject: str
    html: str
    text: str = ""
    cc: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)


class MailAdapter(Protocol):
    name: str

    async def send(self, msg: OutboundMail, idempotency_key: str) -> str:
        """Returns the provider message id."""
        ...


def message_id(idempotency_key: str) -> str:
    # Deterministic Message-ID: even if a retry slipped past the ledger, receivers can dedupe.
    return f"<{hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]}@scrumbot>"


def build_mime(msg: OutboundMail, sender: str, idempotency_key: str) -> EmailMessage:
    em = EmailMessage()
    em["From"] = sender
    em["To"] = ", ".join(msg.to)
    if msg.cc:
        em["Cc"] = ", ".join(msg.cc)
    em["Subject"] = msg.subject
    em["Date"] = formatdate(localtime=True)
    em["Message-ID"] = message_id(idempotency_key) if idempotency_key else make_msgid()
    for k, v in msg.headers.items():
        em[k] = v
    em.set_content(msg.text or "This message needs an HTML-capable mail client.")
    em.add_alternative(msg.html, subtype="html")
    for a in msg.attachments:
        maintype, _, subtype = a.mime.partition("/")
        em.add_attachment(a.content, maintype=maintype, subtype=subtype or "octet-stream", filename=a.filename)
    return em


class SmtpMailAdapter:
    name = "smtp"

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        *,
        username: str | None = None,
        password: str | None = None,
        starttls: bool = False,
    ) -> None:
        self._host, self._port, self._sender = host, port, sender
        self._user, self._password, self._starttls = username, password, starttls

    async def send(self, msg: OutboundMail, idempotency_key: str) -> str:
        em = build_mime(msg, self._sender, idempotency_key)
        await aiosmtplib.send(
            em,
            hostname=self._host,
            port=self._port,
            username=self._user,
            password=self._password,
            start_tls=self._starttls,
            timeout=30,
        )
        return str(em["Message-ID"])


class MemoryMailAdapter:
    """Collects messages in memory (tests)."""

    name = "memory"

    def __init__(self) -> None:
        self.outbox: list[tuple[str, OutboundMail]] = []

    async def send(self, msg: OutboundMail, idempotency_key: str) -> str:
        self.outbox.append((idempotency_key, msg))
        return message_id(idempotency_key)
