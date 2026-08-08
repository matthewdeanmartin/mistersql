"""Persistent one-time resolver for public t.co links."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener


CACHE_VERSION = 1
USER_AGENT = "mistersql-archive-link-resolver/1.0"


def load(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != CACHE_VERSION or not isinstance(value.get("links"), dict):
        raise ValueError("link cache has an unsupported shape")
    if any(not isinstance(key, str) or not isinstance(target, str) for key, target in value["links"].items()):
        raise ValueError("link cache contains a non-string URL")
    return dict(value["links"])


def save(path: Path, links: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps({"version": CACHE_VERSION, "links": dict(sorted(links.items()))}, indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8", newline="\n")
    temporary.replace(path)


class _FirstRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):  # type: ignore[no-untyped-def]
        return None


def _resolve(short_url: str, timeout: float) -> str | None:
    request = Request(short_url, headers={"User-Agent": USER_AGENT}, method="HEAD")
    target: str | None = None
    try:
        with build_opener(_FirstRedirect).open(request, timeout=timeout) as response:
            target = response.headers.get("Location") or response.geturl()
    except HTTPError as error:
        if 300 <= error.code < 400:
            target = error.headers.get("Location")
    except (URLError, TimeoutError, ValueError):
        return None
    if target:
        target = urljoin(short_url, target)
    if target and target.startswith(("http://", "https://")) and "t.co/" not in target:
        return target
    return None


def resolve(urls: Iterable[str], *, workers: int = 8, timeout: float = 12.0) -> dict[str, str]:
    unique = sorted(set(urls))
    resolved: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_resolve, url, timeout): url for url in unique}
        for future in as_completed(futures):
            target = future.result()
            if target:
                resolved[futures[future]] = target
    return resolved
