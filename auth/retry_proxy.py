"""Centralized retry/backoff middleware for Google API 429/503 responses.

Wraps the Google API service's HTTP transport to automatically retry
rate-limited (429) and temporarily unavailable (503) responses with
exponential backoff + jitter, honoring the Retry-After header.

Shape inspired by Mail-0/Zero's reactive retry (apps/server/src/lib/
gmail-rate-limit.ts) but implemented with proper exponential backoff
instead of Mail-0's fixed 60s delays.
"""

import logging
import random
import time

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 5
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 60.0  # seconds
RETRYABLE_STATUSES = (429, 503)


def inject_retry_proxy(service, max_retries=DEFAULT_MAX_RETRIES):
    """Wrap a Google API service's HTTP transport with retry logic.

    Applied after _inject_quota_user so retry wraps the quota-attributed
    request. Safe to use with httplib2 (sync) — Google API calls already
    run in asyncio.to_thread() in this codebase.

    Args:
        service: Google API service object from googleapiclient.discovery.build()
        max_retries: Maximum retry attempts for 429/503 responses.

    Returns:
        The same service object with its HTTP transport wrapped.
    """
    if not hasattr(service, "_http") or not hasattr(service._http, "request"):
        return service
    original_request = service._http.request

    def _retry_request(uri, method="GET", body=None, headers=None, **kwargs):
        last_response = None
        for attempt in range(max_retries + 1):
            response, content = original_request(
                uri, method=method, body=body, headers=headers, **kwargs
            )
            status = int(response.get("status", 200))

            if status not in RETRYABLE_STATUSES:
                return response, content

            last_response = (response, content)

            if attempt == max_retries:
                logger.warning(
                    f"[retry] Exhausted {max_retries} retries for {method} {uri} "
                    f"(last status: {status})"
                )
                return response, content

            # Honor Retry-After header if present
            retry_after = response.get("retry-after")
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = DEFAULT_BASE_DELAY * (2**attempt)
            else:
                delay = DEFAULT_BASE_DELAY * (2**attempt)

            # Add jitter (0.5x to 1.5x) and cap
            delay = delay * (0.5 + random.random())
            delay = min(delay, DEFAULT_MAX_DELAY)

            logger.info(
                f"[retry] {status} on {method} {uri}, "
                f"attempt {attempt + 1}/{max_retries}, "
                f"retrying in {delay:.1f}s"
            )
            time.sleep(delay)

        return last_response

    service._http.request = _retry_request
    return service
