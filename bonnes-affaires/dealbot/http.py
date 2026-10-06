from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} sur {url}")
        self.status = status
        self.body = body


class Session:
    """Petit client HTTP (stdlib uniquement) avec cookies et pause entre requêtes."""

    def __init__(self, min_delay: float = 1.5, timeout: float = 20):
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.min_delay = min_delay
        self.timeout = timeout
        self._last = 0.0

    def _wait(self) -> None:
        # Rester poli avec les sites : pas de rafale de requêtes.
        elapsed = time.monotonic() - self._last
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self._last = time.monotonic()

    def request(self, url: str, *, params=None, headers=None, data=None, method=None) -> str:
        raw, charset = self._fetch(url, params=params, headers=headers, data=data, method=method)
        return raw.decode(charset, errors="replace")

    def request_bytes(self, url: str, max_bytes: int = 50_000_000, **kw) -> bytes:
        return self._fetch(url, max_bytes=max_bytes, **kw)[0]

    def _fetch(self, url: str, *, params=None, headers=None, data=None, method=None,
               max_bytes: int = 20_000_000) -> tuple[bytes, str]:
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        h = {"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}
        h.update(headers or {})
        body = None
        if data is not None:
            body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
        req = urllib.request.Request(url, data=body, headers=h, method=method)
        self._wait()
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read(max_bytes), charset
        except urllib.error.HTTPError as e:
            raise HttpError(e.code, url, e.read().decode("utf-8", "replace")[:500]) from None

    def get_json(self, url: str, **kw):
        headers = {"Accept": "application/json", **kw.pop("headers", {})}
        return json.loads(self.request(url, headers=headers, **kw))
