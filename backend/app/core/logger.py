"""
Application logging setup, including secret redaction.

Prompted by a real incident (see docs/security-findings.md, SECRET-EXPOSURE-01):
a shell command printed a live NVIDIA_API_KEY value into a terminal/tool
transcript. That specific incident was an operator-side command, not a
logging call in this codebase — but it is exactly the failure mode this
filter defends against for anything that *does* go through Python logging:
provider API keys, Authorization/Bearer headers, and cookies must never
reach a log line, even if a future code change accidentally interpolates
one (e.g. `logger.debug("client=%s", client_headers)`).
"""
import logging
import re
import sys

# Known credential shapes seen in this codebase's providers:
# NVIDIA (nvapi-...), OpenAI (sk-...), Anthropic (sk-ant-...), plus generic
# Authorization/Bearer/Cookie headers and an `api_key=...`/`token=...`
# kwarg-style pattern. Each pattern's own capture group is replaced,
# leaving surrounding text (e.g. the header name) intact for readability.
_REDACTIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bnvapi-[A-Za-z0-9_\-]{8,}"), "nvapi-***REDACTED***"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{8,}"), "sk-ant-***REDACTED***"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "sk-***REDACTED***"),
    # Header patterns consume to end-of-line (not just one \S+ token) since
    # "Authorization: Bearer <token>" has a space between scheme and value.
    (re.compile(r"(?i)\b(Authorization)\s*:\s*.+"), r"\1: ***REDACTED***"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+"), "Bearer ***REDACTED***"),
    (re.compile(r"(?i)\b(Cookie|Set-Cookie)\s*:\s*.+"), r"\1: ***REDACTED***"),
    (
        re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*=\s*[^\s&,;'\"]+"),
        r"\1=***REDACTED***",
    ),
]


def redact_secrets(text: str) -> str:
    """The same credential redaction, for strings stored outside the log (e.g. DB error fields)."""
    redacted = text or ""
    for pattern, replacement in _REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


class RedactSecretsFilter(logging.Filter):
    """
    Rewrites `record.msg`/`record.args` so no configured handler can ever
    emit a raw credential, regardless of which module logged it.

    Runs after %-formatting is resolved into a plain string so it catches
    secrets embedded via `%s` args, not just literal f-strings.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = message
        for pattern, replacement in _REDACTIONS:
            redacted = pattern.sub(replacement, redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging() -> logging.Logger:
    """Configure structured, secret-redacting logging for the backend application."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(RedactSecretsFilter())

    if not logger.handlers:
        logger.addHandler(stream_handler)
    else:
        # basicConfig or a prior setup already attached handlers (e.g. under
        # pytest, which configures its own capture handler) — still ensure
        # every existing handler redacts, rather than skipping silently.
        for handler in logger.handlers:
            if not any(isinstance(f, RedactSecretsFilter) for f in handler.filters):
                handler.addFilter(RedactSecretsFilter())

    return logger


log = setup_logging()
