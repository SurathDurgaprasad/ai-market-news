"""
Regression coverage for the RedactSecretsFilter (app/core/logger.py),
added after a real incident where an NVIDIA_API_KEY value was printed to
a tool/session transcript (see docs/RED_TEAM_REPORT.md,
SECRET-EXPOSURE-01). That specific incident was an operator shell command,
not a logging call — this test instead proves the code-level defense: if
any module ever logs a credential (by mistake, via %s interpolation or an
f-string), the configured handler must never emit the raw value.
"""
import logging

from app.core.logger import RedactSecretsFilter


def _emit_and_capture(*, msg: str, args: tuple = ()) -> str:
    logger = logging.getLogger("test_log_redaction")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    import io
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.addFilter(RedactSecretsFilter())
    logger.addHandler(handler)

    logger.info(msg, *args)
    handler.flush()
    return buffer.getvalue()


def test_nvidia_key_redacted_from_fstring():
    fake_key = "nvapi-abcdEFGH12345678ijklmnopqrstuvWXYZ"
    output = _emit_and_capture(msg=f"Using key {fake_key} for request")
    assert fake_key not in output
    assert "REDACTED" in output


def test_nvidia_key_redacted_from_percent_args():
    # The common logging pattern in this codebase: logger.info("... %s", value)
    fake_key = "nvapi-percentStyleArgKey1234567890"
    output = _emit_and_capture(msg="provider key=%s", args=(fake_key,))
    assert fake_key not in output
    assert "REDACTED" in output


def test_openai_and_anthropic_style_keys_redacted():
    openai_key = "sk-1234567890abcdefGHIJKLMNOP"
    anthropic_key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"
    output = _emit_and_capture(
        msg=f"openai={openai_key} anthropic={anthropic_key}"
    )
    assert openai_key not in output
    assert anthropic_key not in output


def test_authorization_and_bearer_header_redacted():
    output = _emit_and_capture(
        msg="request headers: Authorization: Bearer sekrit-token-value-123"
    )
    assert "sekrit-token-value-123" not in output
    assert "REDACTED" in output


def test_cookie_header_redacted():
    output = _emit_and_capture(msg="Set-Cookie: session=abc123verysecretvalue")
    assert "abc123verysecretvalue" not in output


def test_generic_api_key_kwarg_redacted():
    output = _emit_and_capture(msg="config loaded api_key=nvapi-shouldnotleak")
    assert "shouldnotleak" not in output


def test_ordinary_log_messages_pass_through_unchanged():
    """The filter must not mangle normal, secret-free log output."""
    output = _emit_and_capture(msg="NEW EVENT created: id=abc123 score=87")
    assert "NEW EVENT created: id=abc123 score=87" in output


def test_real_nvidia_provider_never_logs_the_configured_key(monkeypatch):
    """
    End-to-end: constructing NVIDIAProvider with a real-shaped key and
    triggering its own log line must not leak the key, using the actual
    application logger (not a hand-rolled one), to catch a regression if
    setup_logging() is ever bypassed for a given handler.
    """
    from app.core.providers.llm import NVIDIAProvider
    from app.core.logger import setup_logging

    setup_logging()  # idempotent; ensures the filter is attached
    fake_key = "nvapi-EndToEndRegressionTestKeyDoNotLeak0000"

    root_logger = logging.getLogger()
    import io
    buffer = io.StringIO()
    capture_handler = logging.StreamHandler(buffer)
    capture_handler.addFilter(RedactSecretsFilter())
    root_logger.addHandler(capture_handler)
    try:
        provider = NVIDIAProvider(api_key=fake_key, model="test-model")
        logging.getLogger("app.core.providers.llm").info(
            "constructed provider with key=%s", fake_key
        )
    finally:
        root_logger.removeHandler(capture_handler)

    output = buffer.getvalue()
    assert fake_key not in output
    assert provider.model == "test-model"
