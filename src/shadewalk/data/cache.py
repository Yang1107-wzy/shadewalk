"""Download cache with a provenance manifest (source URL, time, SHA-256)."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

__all__ = ["cache_dir", "cached_get", "manifest_path"]

USER_AGENT = "shadewalk/0.1 (+https://github.com/Yang1107-wzy/shadewalk)"


def cache_dir() -> Path:
    """Cache root: ``$SHADEWALK_CACHE`` or ``~/.cache/shadewalk``."""
    root = Path(os.environ.get("SHADEWALK_CACHE", Path.home() / ".cache" / "shadewalk"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def manifest_path() -> Path:
    return cache_dir() / "manifest.json"


def _key(url: str, params: dict[str, Any] | None) -> str:
    blob = json.dumps({"url": url, "params": params or {}}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


_LOCK = threading.Lock()


def _record(entry: dict[str, Any]) -> None:
    """Add a manifest entry (thread-safe, atomic replace)."""
    path = manifest_path()
    with _LOCK:
        try:
            data = json.loads(path.read_text()) if path.exists() else {}
        except json.JSONDecodeError:  # pragma: no cover - interrupted earlier write
            data = {}
        data[entry["key"]] = entry
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(path)


def cached_get(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    suffix: str = ".bin",
    refresh: bool = False,
    timeout: float = 180.0,
    retries: int = 3,
    session: requests.Session | None = None,
) -> Path:
    """GET ``url`` once and keep the body on disk.

    The cache file name is derived from the URL and query parameters, and every
    download is logged in ``manifest.json`` with its SHA-256 so results can be
    traced back to the exact source bytes.
    """
    key = _key(url, params)
    target = cache_dir() / "http" / f"{key}{suffix}"
    if target.exists() and not refresh:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    sess = session or requests.Session()
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = sess.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            body = resp.content
            break
        except requests.RequestException as exc:  # pragma: no cover - network dependent
            last_exc = exc
            time.sleep(2**attempt)
    else:  # pragma: no cover - network dependent
        raise RuntimeError(f"failed to download {url}: {last_exc}") from last_exc
    tmp = target.with_suffix(f"{target.suffix}.{os.getpid()}.{threading.get_ident()}.part")
    tmp.write_bytes(body)
    tmp.replace(target)
    _record(
        {
            "key": key,
            "url": url,
            "params": params or {},
            "file": str(target.relative_to(cache_dir())),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    return target
