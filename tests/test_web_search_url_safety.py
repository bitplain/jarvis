from app.services.web_search.url_safety import is_safe_public_http_url


def test_public_https_allowed() -> None:
    assert is_safe_public_http_url("https://example.com/news") is True
    assert is_safe_public_http_url("http://example.com/news") is True


def test_localhost_rejected() -> None:
    assert is_safe_public_http_url("http://localhost:8000") is False
    assert is_safe_public_http_url("https://127.0.0.1/status") is False


def test_private_ip_rejected() -> None:
    assert is_safe_public_http_url("http://10.0.0.5/page") is False
    assert is_safe_public_http_url("http://172.16.0.1/page") is False
    assert is_safe_public_http_url("http://192.168.1.10/page") is False


def test_link_local_and_metadata_rejected() -> None:
    assert is_safe_public_http_url("http://169.254.1.1/page") is False
    assert is_safe_public_http_url("http://169.254.169.254/latest/meta-data") is False


def test_non_http_and_empty_hosts_rejected() -> None:
    assert is_safe_public_http_url("file:///etc/passwd") is False
    assert is_safe_public_http_url("javascript:alert(1)") is False
    assert is_safe_public_http_url("https:///broken") is False
