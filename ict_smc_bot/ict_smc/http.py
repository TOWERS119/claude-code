"""Minimal injectable HTTP transport (standard library only).

Extracted into its own module so every REST client (broker venues, GLM) shares
one transport contract without creating import cycles. A transport is any
callable ``(method, url, headers, body) -> (status, bytes)``; the default uses
``urllib`` and surfaces HTTP error bodies so callers can see why a call failed.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Callable, Optional, Tuple

HttpFn = Callable[[str, str, dict, Optional[bytes]], Tuple[int, bytes]]


def urllib_http(method: str, url: str, headers: dict,
                body: Optional[bytes] = None, timeout: int = 20) -> Tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
