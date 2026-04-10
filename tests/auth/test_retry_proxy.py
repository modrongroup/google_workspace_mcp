"""Tests for centralized retry/backoff middleware.

Verifies that inject_retry_proxy wraps the HTTP transport to automatically
retry 429 (rate limited) and 503 (unavailable) responses with exponential
backoff, jitter, and Retry-After header support.
"""

from unittest.mock import MagicMock, patch

import pytest

from auth.retry_proxy import (
    DEFAULT_BASE_DELAY,
    RETRYABLE_STATUSES,
    inject_retry_proxy,
)


@pytest.fixture
def mock_service():
    """Create a mock Google API service with a controllable HTTP transport."""
    service = MagicMock()
    service._http = MagicMock()
    return service


class TestSuccessPassthrough:
    """Non-retryable responses pass through immediately."""

    @pytest.mark.parametrize("status", ["200", "201", "204", "400", "401", "403", "404"])
    def test_non_retryable_status_returns_immediately(self, mock_service, status):
        """Status codes not in RETRYABLE_STATUSES are returned without retry."""
        original_mock = mock_service._http.request
        original_mock.return_value = ({"status": status}, b"{}")
        inject_retry_proxy(mock_service)

        response, content = mock_service._http.request("https://example.com/api")
        assert response["status"] == status
        assert original_mock.call_count == 1


class TestRetryBehavior:
    """429 and 503 responses trigger retries with backoff."""

    @patch("auth.retry_proxy.time.sleep")
    def test_retries_on_429_then_succeeds(self, mock_sleep, mock_service):
        """429 followed by 200 retries once and returns success."""
        original_mock = mock_service._http.request
        original_mock.side_effect = [
            ({"status": "429"}, b"rate limited"),
            ({"status": "200"}, b'{"ok": true}'),
        ]
        inject_retry_proxy(mock_service)

        response, content = mock_service._http.request("https://example.com/api")
        assert response["status"] == "200"
        assert original_mock.call_count == 2
        assert mock_sleep.call_count == 1

    @patch("auth.retry_proxy.time.sleep")
    def test_retries_on_503_then_succeeds(self, mock_sleep, mock_service):
        """503 followed by 200 retries once and returns success."""
        original_mock = mock_service._http.request
        original_mock.side_effect = [
            ({"status": "503"}, b"unavailable"),
            ({"status": "200"}, b'{"ok": true}'),
        ]
        inject_retry_proxy(mock_service)

        response, content = mock_service._http.request("https://example.com/api")
        assert response["status"] == "200"
        assert original_mock.call_count == 2

    @patch("auth.retry_proxy.time.sleep")
    def test_exhausts_max_retries(self, mock_sleep, mock_service):
        """Persistent 429 exhausts retries and returns the last 429 response."""
        original_mock = mock_service._http.request
        original_mock.return_value = ({"status": "429"}, b"rate limited")
        inject_retry_proxy(mock_service, max_retries=3)

        response, content = mock_service._http.request("https://example.com/api")
        assert response["status"] == "429"
        # Initial attempt + 3 retries = 4 total calls
        assert original_mock.call_count == 4
        assert mock_sleep.call_count == 3


class TestBackoffTiming:
    """Retry delays use exponential backoff with jitter."""

    @patch("auth.retry_proxy.random.random", return_value=0.5)
    @patch("auth.retry_proxy.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep, mock_random, mock_service):
        """Each retry doubles the base delay (with fixed jitter for test)."""
        mock_service._http.request.side_effect = [
            ({"status": "429"}, b""),
            ({"status": "429"}, b""),
            ({"status": "429"}, b""),
            ({"status": "200"}, b"ok"),
        ]
        wrapped = inject_retry_proxy(mock_service, max_retries=3)
        wrapped._http.request("https://example.com/api")

        delays = [call.args[0] for call in mock_sleep.call_args_list]
        # With random()=0.5, jitter multiplier is 1.0, so delays = base * 2^attempt
        assert delays[0] == DEFAULT_BASE_DELAY * (2**0) * 1.0  # 1.0s
        assert delays[1] == DEFAULT_BASE_DELAY * (2**1) * 1.0  # 2.0s
        assert delays[2] == DEFAULT_BASE_DELAY * (2**2) * 1.0  # 4.0s


class TestRetryAfterHeader:
    """Retry-After header value takes precedence over computed backoff."""

    @patch("auth.retry_proxy.random.random", return_value=0.5)
    @patch("auth.retry_proxy.time.sleep")
    def test_honors_retry_after_header(self, mock_sleep, mock_random, mock_service):
        """Retry-After header value is used instead of exponential backoff."""
        mock_service._http.request.side_effect = [
            ({"status": "429", "retry-after": "5"}, b""),
            ({"status": "200"}, b"ok"),
        ]
        wrapped = inject_retry_proxy(mock_service)
        wrapped._http.request("https://example.com/api")

        delay = mock_sleep.call_args[0][0]
        # 5 seconds * jitter(1.0) = 5.0
        assert delay == 5.0

    @patch("auth.retry_proxy.random.random", return_value=0.5)
    @patch("auth.retry_proxy.time.sleep")
    def test_invalid_retry_after_falls_back_to_backoff(
        self, mock_sleep, mock_random, mock_service
    ):
        """Non-numeric Retry-After falls back to exponential backoff."""
        mock_service._http.request.side_effect = [
            ({"status": "429", "retry-after": "invalid"}, b""),
            ({"status": "200"}, b"ok"),
        ]
        wrapped = inject_retry_proxy(mock_service)
        wrapped._http.request("https://example.com/api")

        delay = mock_sleep.call_args[0][0]
        assert delay == DEFAULT_BASE_DELAY * (2**0) * 1.0


class TestServiceIntegrity:
    """inject_retry_proxy returns the same service object."""

    def test_returns_same_service(self, mock_service):
        """Wrapped service is the same object, not a copy."""
        result = inject_retry_proxy(mock_service)
        assert result is mock_service

    def test_retryable_statuses_are_429_and_503(self):
        """Only 429 and 503 are retried."""
        assert RETRYABLE_STATUSES == (429, 503)
