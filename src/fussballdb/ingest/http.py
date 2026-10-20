import hashlib
import json
import time
from pathlib import Path

import httpx

from fussballdb.config import CACHE_DIR

_client = httpx.Client(
    headers={"User-Agent": "Mozilla/5.0 (fussballdb; private research)"},
    timeout=30,
    follow_redirects=True,
)


def get_text(url: str, headers: dict | None = None, cache: bool = False, delay: float = 0.0) -> str:
    """Text holen. Mit cache=True wird die Antwort dauerhaft unter .cache/ abgelegt."""
    path: Path | None = None
    if cache:
        path = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".html")
        if path.exists():
            return path.read_text()
    text = _fetch(url, headers)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    if delay:
        time.sleep(delay)
    return text


RETRY_WAIT = (5, 20, 60)  # Sekunden; Serverfehler und 429 sind bei Transfermarkt meist kurzzeitig


def _fetch(url: str, headers: dict | None = None) -> str:
    for attempt in range(len(RETRY_WAIT) + 1):
        try:
            resp = _client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as exc:
            # 4xx außer 429 ist dauerhaft (z. B. 404), nicht wiederholen
            if exc.response.status_code < 500 and exc.response.status_code != 429:
                raise
            if attempt == len(RETRY_WAIT):
                raise
        except httpx.TransportError:
            if attempt == len(RETRY_WAIT):
                raise
        time.sleep(RETRY_WAIT[attempt])
    raise AssertionError("unreachable")


def get_json(url: str, headers: dict | None = None, cache: bool = False, delay: float = 0.0):
    """JSON holen. Mit cache=True wird die Antwort dauerhaft unter .cache/ abgelegt
    (nur für Daten, die sich nicht mehr ändern, z. B. beendete Spiele)."""
    path: Path | None = None
    if cache:
        path = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".json")
        if path.exists():
            return json.loads(path.read_text())
    data = json.loads(get_text(url, headers))
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    if delay:
        time.sleep(delay)
    return data
