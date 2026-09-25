"""
Regression coverage for CORS-01 (docs/security-findings.md): the API used
to combine allow_origins=["*"] with allow_credentials=True, a known-bad
CORS configuration. Verifies both the config-layer parsing and the
actual middleware behavior against a real TestClient request.
"""
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


def test_cors_allowed_origins_parses_comma_separated_list():
    s = Settings(CORS_ALLOWED_ORIGINS="http://a.example,http://b.example")
    assert s.get_cors_allowed_origins() == ["http://a.example", "http://b.example"]


def test_cors_allowed_origins_strips_whitespace_and_drops_empties():
    s = Settings(CORS_ALLOWED_ORIGINS=" http://a.example ,, http://b.example")
    assert s.get_cors_allowed_origins() == ["http://a.example", "http://b.example"]


def test_cors_allowed_origins_default_is_not_wildcard():
    s = Settings()
    origins = s.get_cors_allowed_origins()
    assert "*" not in origins
    assert origins  # non-empty — a real allowlist, not disabled entirely


def test_cors_preflight_allows_configured_origin_without_credentials():
    client = TestClient(app)
    # Read the actual configured origins straight from Settings to avoid
    # depending on Starlette's internal middleware representation.
    from app.core.config import settings
    origin = settings.get_cors_allowed_origins()[0]

    response = client.options(
        "/api/v1/events/",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
    # No credentials flag should be echoed back — the whole point of CORS-01.
    assert "access-control-allow-credentials" not in {
        k.lower() for k in response.headers.keys()
    }


def test_cors_rejects_unlisted_origin():
    client = TestClient(app)
    response = client.options(
        "/api/v1/events/",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Starlette's CORS middleware returns 200 but omits the
    # allow-origin header for a disallowed origin — the browser is what
    # actually enforces the block, so the assertion is on the header, not
    # the status code.
    assert response.headers.get("access-control-allow-origin") != "http://evil.example"
