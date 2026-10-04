"""URL policy: where API keys may be sent, and which URLs the research tools may fetch."""

import ipaddress
import socket
import urllib.parse

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def require_safe_base_url(base_url):
    """API keys are sent to base_url, so refuse plain http except for a local server."""
    parts = urllib.parse.urlsplit(base_url)
    local = parts.hostname in LOCAL_HOSTS
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError(f"refusing to send an API key to {base_url!r}: base URL must be https (or http on localhost)")


def normalize_url(url):
    """Canonical form for comparing URLs: lowercase scheme and host, no fragment, no trailing slash."""
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip()
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


def _is_public_ip(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_global and not ip.is_multicast


def is_public_url(url, resolve=None):
    """True for http(s) URLs on a public host.

    With `resolve` (socket.getaddrinfo or a fake), a host name must resolve only to public addresses;
    without it only literal IPs and local-looking names are checked (enough to screen search results).
    """
    try:
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:  # malformed brackets or port
        return False
    # Userinfo is refused: the connection could target a different host string than the one checked here.
    if parts.scheme not in ("http", "https") or not host or "@" in parts.netloc:
        return False
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return _is_public_ip(host)
    if resolve is None:
        return True
    try:
        infos = resolve(host, port, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError, ValueError):
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(_is_public_ip(address) for address in addresses)
