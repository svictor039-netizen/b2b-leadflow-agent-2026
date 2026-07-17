"""Safe plain-text template renderer with allowlisted variables only.

No eval, no Jinja, no attribute access, no function calls.
"""

from __future__ import annotations

import re
import unicodedata

from app.core.exceptions import AppError
from app.models.enums import (
    MAX_OUTREACH_BODY,
    MAX_OUTREACH_SUBJECT,
    OUTREACH_TEMPLATE_VARIABLES,
)

_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
# Reject dotted paths, filters, expressions inside braces
_UNSAFE_BRACE_PATTERN = re.compile(r"\{\{[^}]*[.|(\[][^}]*\}\}")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def extract_variables(template: str) -> set[str]:
    return set(_VAR_PATTERN.findall(template))


def _forbid_control_chars(text: str, *, field: str) -> None:
    if _CONTROL_CHARS.search(text) or "\r" in text:
        raise AppError(
            f"{field}: control characters are not allowed",
            status_code=422,
            code="unsafe_template",
        )


def validate_template_text(template: str, *, field: str) -> None:
    _forbid_control_chars(template, field=field)
    if field == "subject" or field == "subject_template":
        if "\n" in template:
            raise AppError(
                f"{field}: newlines are not allowed in subject",
                status_code=422,
                code="unsafe_template",
            )
    if _UNSAFE_BRACE_PATTERN.search(template):
        raise AppError(
            f"{field}: expressions, filters, and attribute access are not allowed",
            status_code=422,
            code="unsafe_template",
        )
    for match in re.finditer(r"\{\{([^}]*)\}\}", template):
        inner = match.group(1).strip()
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", inner):
            raise AppError(
                f"{field}: invalid template expression",
                status_code=422,
                code="unsafe_template",
            )
    unknown = extract_variables(template) - OUTREACH_TEMPLATE_VARIABLES
    if unknown:
        raise AppError(
            f"{field}: unknown template variables: {', '.join(sorted(unknown))}",
            status_code=422,
            code="unknown_template_variable",
        )


def render_template(template: str, context: dict[str, str], *, field: str, max_length: int) -> str:
    validate_template_text(template, field=field)

    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        value = context.get(key, "")
        if value is None:
            return ""
        text = str(value)
        # NFC normalize substituted values; strip CR from values
        text = unicodedata.normalize("NFC", text).replace("\r", "")
        return text

    rendered = _VAR_PATTERN.sub(replacer, template)
    if field in {"subject", "subject_template"} and ("\n" in rendered or "\r" in rendered):
        raise AppError(
            "subject: rendered subject must not contain CR/LF",
            status_code=422,
            code="subject_header_injection",
        )
    if _CONTROL_CHARS.search(rendered):
        raise AppError(
            f"{field}: rendered text contains control characters",
            status_code=422,
            code="unsafe_template",
        )
    # Unicode-aware length: use code points (len) after NFC
    if len(rendered) > max_length:
        raise AppError(
            f"{field}: rendered text exceeds {max_length} characters",
            status_code=422,
            code="rendered_too_long",
        )
    return rendered


def render_subject(template: str, context: dict[str, str]) -> str:
    return render_template(
        template,
        context,
        field="subject",
        max_length=MAX_OUTREACH_SUBJECT,
    )


def render_body(template: str, context: dict[str, str]) -> str:
    return render_template(
        template,
        context,
        field="body",
        max_length=MAX_OUTREACH_BODY,
    )
