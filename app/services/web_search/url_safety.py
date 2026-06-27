import ipaddress
from urllib.parse import urlparse


def is_safe_public_http_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.hostname
    if not host:
        return False
    normalized_host = host.strip().lower()
    if normalized_host in {"localhost", "localhost.localdomain"}:
        return False
    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        return True
    return not (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or str(address) == "169.254.169.254"
    )
