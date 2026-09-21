import pytest
import asyncio
from app.core.fetcher import is_safe_url, fetch_url, resolve_validated_addrinfo
from app.core.urls import sanitize_http_url

def test_ssrf_payloads():
    malicious_urls = [
        "http://127.0.0.1",
        "http://localhost",
        "http://[::1]",
        "http://[::ffff:127.0.0.1]",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://192.168.1.1",
        "http://[fc00::1]",
        "http://169.254.169.254", # AWS metadata
        "http://2130706433", # Decimal 127.0.0.1
        "http://0x7f000001", # Hex 127.0.0.1
        "http://127.1", # Short format
        "http://0177.0.0.1", # Octal format
        "http://0x7f.0.0.1", # Mixed format
        "http://user@127.0.0.1", # Userinfo
        "http://user:pass@127.0.0.1",
        "http://127.0.0.1:22", # Unusual ports
        "HTTP://127.0.0.1", # Mixed case scheme
        "javascript:alert(1)",
        "data:text/html,<body>",
        "file:///etc/passwd",
        "http://127.0.0.1.nip.io", # DNS resolving to 127.0.0.1
        "http://0.0.0.0",
        "http://[0:0:0:0:0:ffff:127.0.0.1]",
    ]

    for url in malicious_urls:
        assert sanitize_http_url(url) == "" or not is_safe_url(url), f"URL bypassed validation: {url}"

def test_fetcher_rejects_ssrf():
    # Attempting to fetch should fail
    with pytest.raises(ValueError, match="Unsafe URL|DNS resolution failed|too large|redirects"):
        fetch_url("http://127.0.0.1.nip.io")

