"""Conservative endpoint locality, shared by memory policy and HTTP transport."""
from ipaddress import ip_address
from urllib.parse import urlsplit


def loopback_endpoint(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or not parsed.hostname:
            return False
        if parsed.hostname.lower() == "localhost":
            return True
        return ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


def local_model(provider: str, base_url: str = "") -> bool:
    # A custom proxy on localhost may forward to a cloud model. Only the explicit
    # Ollama connection type is eligible; remote/LAN Ollama is not "local".
    return provider.casefold() == "ollama" and loopback_endpoint(base_url or "http://localhost:11434/v1")
