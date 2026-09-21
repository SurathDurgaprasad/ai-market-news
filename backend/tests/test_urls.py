from app.core.urls import sanitize_http_url, is_blocked_hostname, is_blocked_ip
import ipaddress


def test_sanitize_rejects_dangerous_schemes():
    assert sanitize_http_url("javascript:alert(1)") == ""
    assert sanitize_http_url("JAVASCRIPT:alert(1)") == ""
    assert sanitize_http_url("  javascript:alert(1)") == ""
    assert sanitize_http_url("data:text/html,<script>x</script>") == ""
    assert sanitize_http_url("file:///etc/passwd") == ""
    assert sanitize_http_url("ftp://example.com/x") == ""
    assert sanitize_http_url("vbscript:msgbox(1)") == ""


def test_sanitize_rejects_percent_encoded_javascript():
    assert sanitize_http_url("javascript%3Aalert(1)") == ""


def test_sanitize_strips_credentials():
    out = sanitize_http_url("https://user:secret@example.com/path")
    assert out == "https://example.com/path"
    assert "secret" not in out
    assert "user" not in out


def test_sanitize_rejects_localhost_and_loopback():
    assert sanitize_http_url("http://localhost/admin") == ""
    assert sanitize_http_url("http://127.0.0.1/admin") == ""
    assert sanitize_http_url("http://[::1]/admin") == ""
    assert sanitize_http_url("http://169.254.169.254/latest/meta-data/") == ""
    assert sanitize_http_url("http://10.0.0.5/internal") == ""
    assert sanitize_http_url("http://192.168.1.1/x") == ""
    assert sanitize_http_url("http://172.16.0.9/x") == ""


def test_sanitize_rejects_scheme_relative_and_empty():
    assert sanitize_http_url("//evil.example.com/x") == ""
    assert sanitize_http_url("") == ""
    assert sanitize_http_url(None) == ""


def test_sanitize_accepts_public_https():
    assert sanitize_http_url("HTTPS://OpenAI.com/blog/gpt-5?utm=1#frag") == "https://openai.com/blog/gpt-5"


def test_sanitize_keeps_query_for_images():
    url = "https://cdn.example.com/img.jpg?w=800&sig=abc"
    assert sanitize_http_url(url, keep_query=True) == "https://cdn.example.com/img.jpg?w=800&sig=abc"


def test_sanitize_rejects_blocked_ports():
    assert sanitize_http_url("https://example.com:22/x") == ""
    assert sanitize_http_url("https://example.com:3306/x") == ""
    assert sanitize_http_url("https://example.com:6379/x") == ""
    assert sanitize_http_url("https://example.com:443/ok") == "https://example.com:443/ok"


def test_sanitize_rejects_decimal_and_short_ip_literals():
    assert sanitize_http_url("http://2130706433/admin") == ""
    assert sanitize_http_url("http://127.1/admin") == ""
    assert sanitize_http_url("http://0x7f000001/admin") == ""


def test_blocked_ip_unspecified_and_mapped():
    assert is_blocked_ip(ipaddress.ip_address("0.0.0.0")) is True
    assert is_blocked_ip(ipaddress.ip_address("::ffff:127.0.0.1")) is True
    assert is_blocked_ip(ipaddress.ip_address("1.1.1.1")) is False
    assert is_blocked_hostname("localhost") is True
    assert is_blocked_hostname("openai.com") is False
