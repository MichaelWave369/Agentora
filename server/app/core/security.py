from urllib.parse import urlparse

from .config import settings


class NetworkGuardError(ValueError):
    pass


def ensure_url_allowed(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ''
    mode = settings.agentora_network_mode
    if mode == 'offline':
        raise NetworkGuardError('Network mode is offline; outbound HTTP disabled')
    if mode == 'localhost_only' and host not in {'localhost', '127.0.0.1'}:
        raise NetworkGuardError(f'Host {host} blocked in localhost_only mode')
    if mode == 'allowlist' and host not in set(settings.allowed_hosts):
        raise NetworkGuardError(f'Host {host} not in allowlist')
