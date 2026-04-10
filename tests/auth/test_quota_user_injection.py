"""Tests for quotaUser injection on Google API requests.

Verifies that _inject_quota_user wraps the HTTP transport to append
quotaUser=<email> on every request, preventing multi-tenant deployments
from exhausting the project's global quota bucket.
"""

import urllib.parse
from unittest.mock import MagicMock

import pytest

from auth.service_decorator import _inject_quota_user


@pytest.fixture
def mock_service():
    """Create a mock Google API service with a trackable HTTP transport."""
    service = MagicMock()
    service._http = MagicMock()
    service._http.request = MagicMock(return_value=({"status": "200"}, b"{}"))
    return service


class TestQuotaUserInjection:
    """_inject_quota_user must append quotaUser to every request URI."""

    def test_appends_quota_user_to_uri_without_query(self, mock_service):
        """URI with no query string gets ?quotaUser=email."""
        email = "user@example.com"
        original_mock = mock_service._http.request
        _inject_quota_user(mock_service, email)
        mock_service._http.request("https://gmail.googleapis.com/v1/users/me/messages")

        actual_uri = original_mock.call_args[0][0]
        assert f"quotaUser={urllib.parse.quote(email)}" in actual_uri
        assert "?" in actual_uri

    def test_appends_quota_user_to_uri_with_existing_query(self, mock_service):
        """URI with existing query string gets &quotaUser=email."""
        email = "user@example.com"
        original_mock = mock_service._http.request
        _inject_quota_user(mock_service, email)
        mock_service._http.request(
            "https://gmail.googleapis.com/v1/users/me/messages?maxResults=10"
        )

        actual_uri = original_mock.call_args[0][0]
        assert "&quotaUser=" in actual_uri
        assert "?maxResults=10" in actual_uri

    def test_url_encodes_email_with_special_characters(self, mock_service):
        """Email addresses with + or other special chars are URL-encoded."""
        email = "user+tag@example.com"
        original_mock = mock_service._http.request
        _inject_quota_user(mock_service, email)
        mock_service._http.request("https://gmail.googleapis.com/v1/users/me/messages")

        actual_uri = original_mock.call_args[0][0]
        assert "user%2Btag%40example.com" in actual_uri

    def test_noop_when_email_is_none(self, mock_service):
        """None email returns the service unmodified."""
        original_request = mock_service._http.request
        result = _inject_quota_user(mock_service, None)
        assert result._http.request is original_request

    def test_noop_when_email_is_empty_string(self, mock_service):
        """Empty string email returns the service unmodified."""
        original_request = mock_service._http.request
        result = _inject_quota_user(mock_service, "")
        assert result._http.request is original_request

    def test_returns_same_service_object(self, mock_service):
        """The returned service is the same object, not a copy."""
        result = _inject_quota_user(mock_service, "user@example.com")
        assert result is mock_service

    def test_preserves_original_response(self, mock_service):
        """Wrapped request returns the original response unchanged."""
        expected_response = ({"status": "200"}, b'{"messages": []}')
        mock_service._http.request.return_value = expected_response

        wrapped = _inject_quota_user(mock_service, "user@example.com")
        response = wrapped._http.request("https://example.com/api")
        assert response == expected_response
