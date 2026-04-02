"""Tests for slack_search module"""

import pytest
from unittest.mock import MagicMock, patch
from slack_sdk.errors import SlackApiError

from slack_search import (
    SlackSearchError,
    build_query,
    handle_rate_limit,
    search_all_messages,
    search_messages,
)


# --- build_query ---


class TestBuildQuery:
    def test_keyword_only(self):
        assert build_query(keyword="hello") == '"hello"'

    def test_channel_id_and_keyword(self):
        assert build_query(channel_id="C123", keyword="hello") == 'in:<#C123> "hello"'

    def test_channel_name_and_keyword(self):
        assert build_query(channel_id="times_hihats", keyword="hello") == 'in:times_hihats "hello"'

    def test_keyword_and_after_date(self):
        assert build_query(keyword="hello", after_date="2025-01-01") == '"hello" after:2025-01-01'

    def test_all_params(self):
        result = build_query(keyword="hello", channel_id="C123", after_date="2025-01-01")
        assert result == 'in:<#C123> "hello" after:2025-01-01'

    def test_extra_mention(self):
        result = build_query(extra="<@U456>", after_date="2025-01-01")
        assert result == "<@U456> after:2025-01-01"

    def test_extra_with_channel_id(self):
        result = build_query(extra="<@U456>", channel_id="C123")
        assert result == "in:<#C123> <@U456>"

    def test_extra_with_channel_name(self):
        result = build_query(extra="<@U456>", channel_id="general")
        assert result == "in:general <@U456>"

    def test_channel_id_only(self):
        assert build_query(channel_id="C123") == "in:<#C123>"

    def test_channel_name_only(self):
        assert build_query(channel_id="general") == "in:general"

    def test_exact_match_false(self):
        assert build_query(keyword="AI", exact_match=False) == "ai"

    def test_exact_match_false_with_channel(self):
        result = build_query(keyword="AI", channel_id="C123", exact_match=False)
        assert result == "in:<#C123> ai"

    def test_keyword_lowercased(self):
        assert build_query(keyword="OpenClaw") == '"openclaw"'

    def test_keyword_lowercased_exact_match_false(self):
        assert build_query(keyword="OpenClaw", exact_match=False) == "openclaw"


# --- handle_rate_limit ---


def _make_slack_error(error_code, status_code=200, retry_after=1):
    """SlackApiError のモックを生成するヘルパー"""
    resp = MagicMock()
    resp.__getitem__ = lambda self, key: error_code if key == "error" else None
    resp.status_code = status_code
    resp.headers = {"Retry-After": str(retry_after)}
    return SlackApiError("error", resp)


class TestHandleRateLimit:
    def test_success_on_first_try(self):
        func = MagicMock(return_value="ok")
        result = handle_rate_limit(func, "arg1", key="val")
        assert result == "ok"
        func.assert_called_once_with("arg1", key="val")

    @patch("slack_search.time.sleep")
    def test_retry_then_success(self, mock_sleep):
        func = MagicMock(
            side_effect=[_make_slack_error("ratelimited", 429, 1), "ok"]
        )
        result = handle_rate_limit(func, max_retries=3)
        assert result == "ok"
        assert func.call_count == 2
        mock_sleep.assert_called_once_with(1)

    @patch("slack_search.time.sleep")
    def test_max_retries_exceeded(self, mock_sleep):
        func = MagicMock(
            side_effect=_make_slack_error("ratelimited", 429, 1)
        )
        with pytest.raises(SlackApiError):
            handle_rate_limit(func, max_retries=2)
        assert func.call_count == 2

    def test_non_ratelimit_error_raises_immediately(self):
        func = MagicMock(side_effect=_make_slack_error("missing_scope"))
        with pytest.raises(SlackApiError):
            handle_rate_limit(func)
        func.assert_called_once()


# --- search_messages generator ---


def _mock_search_response(matches, page=1, page_count=1):
    """search_messages API レスポンスのモックを生成"""
    resp = MagicMock()
    data = {
        "ok": True,
        "messages": {
            "matches": matches,
            "pagination": {
                "page": page,
                "page_count": page_count,
                "total_count": len(matches) * page_count,
            },
        },
    }
    resp.__getitem__ = lambda self, key: data[key]
    resp.__bool__ = lambda self: True
    resp.get = lambda key, default=None: data.get(key, default)
    return resp


class TestSearchMessages:
    @patch("slack_search.time.sleep")
    def test_single_page(self, mock_sleep):
        client = MagicMock()
        client.search_messages.return_value = _mock_search_response(
            [{"text": "msg1"}], page=1, page_count=1
        )
        pages = list(search_messages(client, "query"))
        assert len(pages) == 1
        assert pages[0] == [{"text": "msg1"}]

    @patch("slack_search.time.sleep")
    def test_multiple_pages(self, mock_sleep):
        client = MagicMock()
        client.search_messages.side_effect = [
            _mock_search_response([{"text": "p1"}], page=1, page_count=3),
            _mock_search_response([{"text": "p2"}], page=2, page_count=3),
            _mock_search_response([{"text": "p3"}], page=3, page_count=3),
        ]
        pages = list(search_messages(client, "query"))
        assert len(pages) == 3
        assert pages[1] == [{"text": "p2"}]

    @patch("slack_search.time.sleep")
    def test_empty_result(self, mock_sleep):
        client = MagicMock()
        client.search_messages.return_value = _mock_search_response([], page=1, page_count=1)
        pages = list(search_messages(client, "query"))
        assert len(pages) == 1
        assert pages[0] == []

    @patch("slack_search.time.sleep")
    def test_max_pages_limit(self, mock_sleep):
        client = MagicMock()
        client.search_messages.side_effect = [
            _mock_search_response([{"text": f"p{i}"}], page=i, page_count=100)
            for i in range(1, 5)
        ]
        pages = list(search_messages(client, "query", max_pages=2))
        assert len(pages) == 2

    def test_missing_scope_raises_search_error(self):
        client = MagicMock()
        client.search_messages.side_effect = _make_slack_error("missing_scope")
        with pytest.raises(SlackSearchError, match="search:read"):
            list(search_messages(client, "query"))

    @patch("slack_search.time.sleep")
    def test_ratelimit_retried(self, mock_sleep):
        """handle_rate_limit 経由でリトライされることの確認"""
        client = MagicMock()
        client.search_messages.side_effect = [
            _make_slack_error("ratelimited", 429, 1),
            _mock_search_response([{"text": "ok"}], page=1, page_count=1),
        ]
        pages = list(search_messages(client, "query"))
        assert len(pages) == 1
        assert pages[0] == [{"text": "ok"}]


# --- search_all_messages ---


class TestSearchAllMessages:
    @patch("slack_search.time.sleep")
    def test_flattens_multiple_pages(self, mock_sleep):
        client = MagicMock()
        client.search_messages.side_effect = [
            _mock_search_response([{"text": "a"}, {"text": "b"}], page=1, page_count=2),
            _mock_search_response([{"text": "c"}], page=2, page_count=2),
        ]
        result = search_all_messages(client, "query")
        assert result == [{"text": "a"}, {"text": "b"}, {"text": "c"}]

    @patch("slack_search.time.sleep")
    def test_empty(self, mock_sleep):
        client = MagicMock()
        client.search_messages.return_value = _mock_search_response([], page=1, page_count=1)
        result = search_all_messages(client, "query")
        assert result == []
