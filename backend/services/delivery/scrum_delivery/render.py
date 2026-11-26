"""Jinja2 rendering for emails and the daily report; WeasyPrint for the PDF when available."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger(__name__)
TEMPLATES = Path(__file__).parent / "templates"


@lru_cache
def env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render(template: str, **ctx: Any) -> str:
    return env().get_template(template).render(**ctx)


def long_date(d: date) -> str:
    return f"{d:%A}, {d.day} {d:%B %Y}"


def _pdf_sync(html: str) -> bytes | None:
    try:
        from weasyprint import HTML  # optional: needs Pango (present in the Docker image)
    except (ImportError, OSError) as exc:
        log.info("PDF rendering skipped (WeasyPrint unavailable: %s)", exc.__class__.__name__)
        return None
    return HTML(string=html).write_pdf()  # type: ignore[no-any-return]


async def html_to_pdf(html: str) -> bytes | None:
    return await asyncio.to_thread(_pdf_sync, html)


def text_version(lines: list[str]) -> str:
    return "\n".join(lines)
