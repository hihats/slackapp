"""Tests for channel_daily_posts module"""

import json
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from channel_daily_posts import (
    get_channel_messages,
    get_thread_replies,
    format_message_data,
    parse_date,
    parse_days,
)


def _make_history_response(messages, has_more=False, next_cursor=None):
    """conversations_history レスポンスのモックを生成"""
    data = {
        "ok": True,
        "messages": messages,
        "has_more": has_more,
        "response_metadata": {"next_cursor": next_cursor or ""},
    }
    resp = MagicMock()
    resp.__getitem__ = lambda self, key: data[key]
    resp.__bool__ = lambda self: True
    resp.get = lambda key, default=None: data.get(key, default)
    return resp


def _make_replies_response(messages, has_more=False, next_cursor=None):
    """conversations_replies レスポンスのモックを生成"""
    return _make_history_response(messages, has_more, next_cursor)


# --- get_channel_messages ---


class TestGetChannelMessages:
    @patch("channel_daily_posts.time.sleep")
    def test_single_page(self, mock_sleep):
        """1ページ分のメッセージを全て返す"""
        client = MagicMock()
        msgs = [{"ts": "100.0", "text": "a"}, {"ts": "101.0", "text": "b"}]
        client.conversations_history.return_value = _make_history_response(msgs)

        result = get_channel_messages(client, "C123", 99.0, 200.0)

        assert len(result) == 2
        assert result[0]["text"] == "a"
        assert result[1]["text"] == "b"

    @patch("channel_daily_posts.time.sleep")
    def test_multiple_pages(self, mock_sleep):
        """複数ページにまたがるメッセージを全て返す"""
        client = MagicMock()
        page1 = [{"ts": "100.0", "text": "a"}]
        page2 = [{"ts": "101.0", "text": "b"}]
        client.conversations_history.side_effect = [
            _make_history_response(page1, has_more=True, next_cursor="cursor1"),
            _make_history_response(page2),
        ]

        result = get_channel_messages(client, "C123", 99.0, 200.0)

        assert len(result) == 2
        assert result[0]["text"] == "a"
        assert result[1]["text"] == "b"

    @patch("channel_daily_posts.time.sleep")
    def test_empty_channel(self, mock_sleep):
        """メッセージがない場合は空リスト"""
        client = MagicMock()
        client.conversations_history.return_value = _make_history_response([])

        result = get_channel_messages(client, "C123", 99.0, 200.0)
        assert result == []

    @patch("channel_daily_posts.time.sleep")
    def test_passes_oldest_and_latest(self, mock_sleep):
        """oldest と latest パラメータが正しく渡される"""
        client = MagicMock()
        client.conversations_history.return_value = _make_history_response([])

        get_channel_messages(client, "C123", 1000.0, 2000.0)

        call_kwargs = client.conversations_history.call_args[1]
        assert call_kwargs["oldest"] == str(1000.0)
        assert call_kwargs["latest"] == str(2000.0)
        assert call_kwargs["channel"] == "C123"


# --- get_thread_replies ---


class TestGetThreadReplies:
    @patch("channel_daily_posts.time.sleep")
    def test_excludes_parent_message(self, mock_sleep):
        """親メッセージ（先頭）を除外して返す"""
        client = MagicMock()
        parent = {"ts": "100.0", "text": "parent"}
        reply1 = {"ts": "100.1", "text": "reply1"}
        reply2 = {"ts": "100.2", "text": "reply2"}
        client.conversations_replies.return_value = _make_replies_response(
            [parent, reply1, reply2]
        )

        result = get_thread_replies(client, "C123", "100.0")

        assert len(result) == 2
        assert result[0]["text"] == "reply1"
        assert result[1]["text"] == "reply2"

    @patch("channel_daily_posts.time.sleep")
    def test_multiple_pages_excludes_parent_only_on_first(self, mock_sleep):
        """複数ページの場合、親メッセージは最初のページでのみ除外"""
        client = MagicMock()
        page1 = [{"ts": "100.0", "text": "parent"}, {"ts": "100.1", "text": "r1"}]
        page2 = [{"ts": "100.2", "text": "r2"}]
        client.conversations_replies.side_effect = [
            _make_replies_response(page1, has_more=True, next_cursor="cur1"),
            _make_replies_response(page2),
        ]

        result = get_thread_replies(client, "C123", "100.0")

        assert len(result) == 2
        assert result[0]["text"] == "r1"
        assert result[1]["text"] == "r2"

    @patch("channel_daily_posts.time.sleep")
    def test_no_replies(self, mock_sleep):
        """返信がない場合は空リスト"""
        client = MagicMock()
        client.conversations_replies.return_value = _make_replies_response([])

        result = get_thread_replies(client, "C123", "100.0")
        assert result == []


# --- parse_date ---


class TestParseDate:
    def test_valid_date(self):
        """正常な日付文字列をパースできる"""
        oldest, latest = parse_date("2024-06-15")
        assert oldest is not None
        assert latest is not None
        assert latest > oldest

    def test_invalid_date_returns_none(self):
        """不正な日付文字列は (None, None)"""
        oldest, latest = parse_date("not-a-date")
        assert oldest is None
        assert latest is None


# --- parse_days ---


class TestParseDays:
    def test_valid_days(self):
        """正の整数で開始・終了タイムスタンプを返す"""
        oldest, latest = parse_days(7)
        assert oldest is not None
        assert latest is not None
        assert latest > oldest

    def test_zero_days_returns_none(self):
        """0日はエラー"""
        oldest, latest = parse_days(0)
        assert oldest is None
        assert latest is None


# --- format_message_data ---


class TestFormatMessageData:
    def test_formats_message_correctly(self):
        """メッセージを正しくフォーマットする"""
        message = {
            "ts": "1700000000.000000",
            "user": "U123",
            "text": "hello world",
            "thread_ts": None,
            "reply_count": 0,
            "reactions": [],
            "attachments": [],
            "files": [],
            "blocks": [],
        }
        channel_info = {"id": "C123", "name": "general"}
        user_cache = {
            "U123": {
                "name": "testuser",
                "profile": {"display_name": "Test User"},
            }
        }

        result = format_message_data(message, channel_info, user_cache, "message")

        assert result["channel_id"] == "C123"
        assert result["channel_name"] == "general"
        assert result["user_id"] == "U123"
        assert result["user_name"] == "testuser"
        assert result["text"] == "hello world"
        assert result["type"] == "message"
