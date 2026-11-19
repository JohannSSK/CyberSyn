"""Per-process sliding window for failed credential operations (one web worker)."""

import math
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import make_response, request

from config import _env_flag
from errors import ApiError
from web import get_json_dict

WINDOW = 300
MAX_ATTEMPTS = 10
_lock = threading.Lock()
_attempts = defaultdict(deque)
_sweep = 0


def reset():
    with _lock:
        _attempts.clear()


def limited(fail, methods=None):
    def decorate(fn):
        @wraps(fn)
        def guarded():
            if not _env_flag("CYBERSYN_RATE_LIMIT", True):
                return fn()
            data = get_json_dict() or {}
            if methods and str(data.get("method")).strip().lower() not in methods:
                return fn()
            ip = request.remote_addr
            if _env_flag("CYBERSYN_TRUST_PROXY"):
                forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
                if forwarded:
                    ip = forwarded
            name = str(data.get("username") or data.get("Employee_id") or "").strip().lower()[:64]
            keys = [(ip,), (ip, name)]
            global _sweep
            with _lock:
                now = time.monotonic()
                if now >= _sweep:
                    for key in list(_attempts):
                        if not _attempts[key] or _attempts[key][-1] <= now - WINDOW:
                            del _attempts[key]
                    _sweep = now + WINDOW
                for key in keys:
                    q = _attempts[key]
                    while q and q[0] <= now - WINDOW:
                        q.popleft()
                    if len(q) >= MAX_ATTEMPTS:
                        response = make_response(fail("Too many attempts. Try again later.", 429))
                        response.headers["Retry-After"] = str(max(1, math.ceil(q[0] + WINDOW - now)))
                        return response
                # Reserve capacity before scrypt so simultaneous attempts count too.
                for key in keys:
                    _attempts[key].append(now)
            failed_auth = False
            try:
                response = make_response(fn())
                failed_auth = response.status_code in (401, 403)
                return response
            except ApiError as exc:
                failed_auth = exc.status in (401, 403)
                raise
            finally:
                if not failed_auth:
                    with _lock:
                        for key in keys:
                            q = _attempts.get(key)
                            if q and now in q:
                                q.remove(now)
                                if not q:
                                    del _attempts[key]
        return guarded
    return decorate
