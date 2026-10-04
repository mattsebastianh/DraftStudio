"""URL policy: where API keys may be sent."""

import urllib.parse

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def require_safe_base_url(base_url):
    """API keys are sent to base_url, so refuse plain http except for a local server."""
    parts = urllib.parse.urlsplit(base_url)
    local = parts.hostname in LOCAL_HOSTS
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError(f"refusing to send an API key to {base_url!r}: base URL must be https (or http on localhost)")
