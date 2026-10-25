"""Resilient HTTP client with retry on 429 (rate limit) and 503 (transient failure).

Zero external dependencies; uses Python's standard library urllib.

Retry policy:
- 429 is always safe to retry: the server refused the request without processing it.
  The client honours Retry-After.
- GETs are retried on 503 and network errors.
- Writes (POST) are retried on 503 / network errors only when the caller says the
  call is idempotent (`idempotent=True`, e.g. the terminal charge keyed by order_ref).
  Otherwise the client raises AmbiguousWriteError, because the write may have been
  applied. The caller then checks the backend before trying again (see ShopifyAdapter).
"""

import json
import logging
import socket
import time
import urllib.request
import urllib.error
from typing import Any, Dict, Optional
from pos.config import MAX_RETRIES, DEFAULT_RETRY_AFTER_SECS, HTTP_TIMEOUT_SECS

logger = logging.getLogger("eluno.pos.http")


class HttpStatusError(Exception):
    """Non-retryable HTTP error response (4xx / exhausted 5xx)."""

    def __init__(self, url: str, code: int, body: Any):
        super().__init__(f"HTTP {code} from {url}: {body}")
        self.url = url
        self.code = code
        self.body = body


class AmbiguousWriteError(Exception):
    """A write timed out or failed mid-flight; it may or may not have been applied."""

    def __init__(self, url: str, cause: Exception):
        super().__init__(f"Write to {url} has unknown outcome: {cause}")
        self.url = url
        self.cause = cause


class ResilientHttpClient:
    """HTTP client resilient to rate limits (429) and transient server errors (503)."""

    def __init__(self, max_retries: int = MAX_RETRIES, timeout: float = HTTP_TIMEOUT_SECS):
        self.max_retries = max_retries
        self.timeout = timeout

    def request(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotent: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Execute an HTTP request with the retry policy described in the module docstring."""
        method = method.upper()
        safe_to_repeat = (method == "GET") if idempotent is None else idempotent
        all_headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "ElunoPOS/1.0",
        }
        if headers:
            all_headers.update(headers)

        data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None

        retries = 0
        backoff = 0.5

        while True:
            req = urllib.request.Request(url=url, data=data_bytes, headers=all_headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    res_body = response.read().decode("utf-8")
                    if not res_body.strip():
                        return {}
                    return json.loads(res_body)

            except urllib.error.HTTPError as exc:
                code = exc.code
                try:
                    error_body = exc.read().decode("utf-8")
                except Exception:
                    error_body = ""
                try:
                    parsed_err: Any = json.loads(error_body)
                except Exception:
                    parsed_err = {"error": error_body}

                retryable = code == 429 or (code in (502, 503, 504) and safe_to_repeat)
                if retryable and retries < self.max_retries:
                    retries += 1
                    retry_after = DEFAULT_RETRY_AFTER_SECS
                    header_val = exc.headers.get("Retry-After") if exc.headers else None
                    if header_val:
                        try:
                            retry_after = float(header_val)
                        except ValueError:
                            pass
                    sleep_time = retry_after if code == 429 else max(retry_after, backoff)
                    logger.warning(
                        "HTTP %s from %s. Retrying in %.2fs (attempt %d/%d)",
                        code, url, sleep_time, retries, self.max_retries,
                    )
                    time.sleep(sleep_time)
                    backoff *= 1.5
                    continue

                if code >= 500 and not safe_to_repeat:
                    raise AmbiguousWriteError(url, HttpStatusError(url, code, parsed_err))
                raise HttpStatusError(url, code, parsed_err)

            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
                if not safe_to_repeat:
                    raise AmbiguousWriteError(url, exc)
                if retries < self.max_retries:
                    retries += 1
                    logger.warning("Network error %s on %s. Retrying in %.2fs", exc, url, backoff)
                    time.sleep(backoff)
                    backoff *= 1.5
                    continue
                raise

    def get(self, url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        return self.request("GET", url, headers=headers)

    def post(
        self,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotent: bool = False,
    ) -> Dict[str, Any]:
        return self.request("POST", url, payload=payload, headers=headers, idempotent=idempotent)
