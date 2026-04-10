"""Tests for folder-aware search query normalizer.

Verifies that _normalize_search rewrites folder names into Gmail search
operators so skill authors don't need to memorize the Gmail DSL.
"""

import pytest

from gmail.gmail_tools import _normalize_search


class TestFolderMapping:
    """Each supported folder maps to the correct Gmail search operator."""

    @pytest.mark.parametrize(
        "folder,expected_prefix",
        [
            ("inbox", "in:inbox"),
            ("archive", "in:archive"),
            ("trash", "in:trash"),
            ("drafts", "is:draft"),
            ("sent", "in:sent"),
            ("spam", "in:spam"),
            ("starred", "is:starred"),
            ("unread", "is:unread"),
            ("important", "is:important"),
        ],
    )
    def test_folder_maps_to_operator(self, folder, expected_prefix):
        """Each folder name produces the correct Gmail operator."""
        result = _normalize_search(folder, "test query")
        assert result.startswith(expected_prefix)

    @pytest.mark.parametrize("folder", ["inbox", "INBOX", "Inbox", "InBox"])
    def test_folder_is_case_insensitive(self, folder):
        """Folder names are matched case-insensitively."""
        result = _normalize_search(folder, "test")
        assert "in:inbox" in result


class TestQueryCombination:
    """Folder operators are combined with the query using AND."""

    def test_folder_with_query_uses_and(self):
        """Non-empty query is wrapped in AND parentheses."""
        result = _normalize_search("inbox", "from:alice@example.com")
        assert result == "in:inbox AND (from:alice@example.com)"

    def test_folder_with_empty_query_returns_operator_only(self):
        """Empty query returns just the folder operator."""
        result = _normalize_search("inbox", "")
        assert result == "in:inbox"

    def test_folder_with_whitespace_query_returns_operator_only(self):
        """Whitespace-only query returns just the folder operator."""
        result = _normalize_search("inbox", "   ")
        assert result == "in:inbox"


class TestPassthrough:
    """No folder means the query passes through unchanged."""

    def test_none_folder_returns_query_unchanged(self):
        """None folder passes the query through."""
        query = "from:bob@example.com has:attachment"
        assert _normalize_search(None, query) == query

    def test_empty_string_folder_returns_query_unchanged(self):
        """Empty string folder passes the query through."""
        query = "subject:meeting"
        assert _normalize_search("", query) == query


class TestInvalidFolder:
    """Unknown folder names raise ValueError with valid options."""

    def test_unknown_folder_raises_value_error(self):
        """Unrecognized folder name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown folder"):
            _normalize_search("outbox", "test")

    def test_error_message_lists_valid_folders(self):
        """ValueError message includes the valid folder names."""
        with pytest.raises(ValueError, match="inbox") as exc_info:
            _normalize_search("nonexistent", "test")
        # Should list multiple valid folders
        error_msg = str(exc_info.value)
        assert "archive" in error_msg
        assert "trash" in error_msg
