"""Tests for weekly_message_count module"""

import pytest
from unittest.mock import MagicMock, patch

from weekly_message_count import (
    fetch_messages,
    get_sunday_week_key,
    aggregate_by_week,
)


def _make_response(messages, has_more=False, next_cursor=None):
    """conversations API レスポンスのモックを生成"""
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


# --- fetch_messages ---


class TestFetchMessages:
    @patch("weekly_message_count.time.sleep")
    def test_keyword_filter_on_parent_messages(self, mock_sleep):
        """親メッセージからキーワードに一致するものだけを返す"""
        client = MagicMock()
        msgs = [
            {"ts": "100.0", "text": "hello world", "reply_count": 0},
            {"ts": "101.0", "text": "no match here", "reply_count": 0},
            {"ts": "102.0", "text": "say Hello again", "reply_count": 0},
        ]
        client.conversations_history.return_value = _make_response(msgs)

        result = fetch_messages(client, "C123", "hello", 30)

        assert len(result) == 2
        assert result[0]["ts"] == "100.0"
        assert result[1]["ts"] == "102.0"

    @patch("weekly_message_count.time.sleep")
    def test_keyword_filter_on_thread_replies(self, mock_sleep):
        """スレッド返信からもキーワードに一致するものを返す"""
        client = MagicMock()
        parent = {"ts": "100.0", "text": "no match", "reply_count": 1}
        client.conversations_history.return_value = _make_response([parent])

        reply_parent = {"ts": "100.0", "text": "no match"}
        reply1 = {"ts": "100.1", "text": "hello from thread"}
        reply2 = {"ts": "100.2", "text": "no match reply"}
        client.conversations_replies.return_value = _make_response(
            [reply_parent, reply1, reply2]
        )

        result = fetch_messages(client, "C123", "hello", 30)

        assert len(result) == 1
        assert result[0]["ts"] == "100.1"

    @patch("weekly_message_count.time.sleep")
    def test_deduplication_by_text(self, mock_sleep):
        """同じテキストのメッセージは重複排除される"""
        client = MagicMock()
        msgs = [
            {"ts": "100.0", "text": "hello", "reply_count": 0},
            {"ts": "101.0", "text": "Hello", "reply_count": 0},
        ]
        client.conversations_history.return_value = _make_response(msgs)

        result = fetch_messages(client, "C123", "hello", 30)

        # "hello" と "Hello" は .strip().lower() で同一 → 重複排除
        assert len(result) == 1

    @patch("weekly_message_count.time.sleep")
    def test_empty_channel(self, mock_sleep):
        """メッセージがない場合は空リスト"""
        client = MagicMock()
        client.conversations_history.return_value = _make_response([])

        result = fetch_messages(client, "C123", "hello", 30)
        assert result == []

    @patch("weekly_message_count.time.sleep")
    def test_parent_message_skipped_in_replies(self, mock_sleep):
        """スレッド返信の先頭（親メッセージ）はスキップされる"""
        client = MagicMock()
        parent = {"ts": "100.0", "text": "hello parent", "reply_count": 1}
        client.conversations_history.return_value = _make_response([parent])

        # replies の先頭は親メッセージ
        reply_parent = {"ts": "100.0", "text": "hello parent"}
        reply1 = {"ts": "100.1", "text": "hello reply"}
        client.conversations_replies.return_value = _make_response(
            [reply_parent, reply1]
        )

        result = fetch_messages(client, "C123", "hello", 30)

        # 親は history から1件、reply から1件。親テキストは重複排除で1件のみ
        texts = [m["text"] for m in result]
        assert "hello parent" in texts
        assert "hello reply" in texts


# --- get_sunday_week_key ---


class TestGetSundayWeekKey:
    def test_sunday_is_start_of_week(self):
        """日曜日は週の始まり"""
        # 2024-06-16 is Sunday
        ts = 1718496000.0  # 2024-06-16 00:00:00 UTC
        week_key, start_date, end_date = get_sunday_week_key(ts)

        assert start_date.weekday() == 6  # Sunday

    def test_returns_week_key_format(self):
        """YYYY-Www 形式の週キーを返す"""
        ts = 1718496000.0
        week_key, _, _ = get_sunday_week_key(ts)

        assert "-W" in week_key


# --- aggregate_by_week ---


class TestAggregateByWeek:
    def test_counts_messages_per_week(self):
        """週ごとにメッセージを集計する"""
        messages = [
            {"ts": "1718496000.0"},  # 2024-06-16 (Sun)
            {"ts": "1718582400.0"},  # 2024-06-17 (Mon) - same week
            {"ts": "1719100800.0"},  # 2024-06-23 (Sun) - next week
        ]

        result = aggregate_by_week(messages)

        total_count = sum(v["count"] for v in result.values())
        assert total_count == 3

    def test_empty_messages(self):
        """空リストは空の集計結果"""
        result = aggregate_by_week([])
        assert result == {}
