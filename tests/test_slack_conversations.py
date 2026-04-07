"""Tests for slack_conversations module"""

from unittest.mock import MagicMock, call, patch

import pytest
from slack_sdk.errors import SlackApiError

from slack_conversations import (
    fetch_all_channel_history,
    fetch_all_thread_replies,
    fetch_channel_history,
    fetch_thread_replies,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_history_response(messages, has_more=False, next_cursor=None):
    """conversations.history / conversations.replies レスポンスのモック"""
    data = {
        "ok": True,
        "messages": messages,
        "has_more": has_more,
        "response_metadata": {"next_cursor": next_cursor or ""},
    }
    resp = MagicMock()
    resp.get = lambda key, default=None: data.get(key, default)
    resp.__getitem__ = lambda self, key: data[key]
    resp.__bool__ = lambda self: True
    return resp


def _make_slack_error(error_code, status_code=200, retry_after=1):
    """SlackApiError のモックを生成するヘルパー"""
    resp = MagicMock()
    resp.__getitem__ = lambda self, key: error_code if key == "error" else None
    resp.status_code = status_code
    resp.headers = {"Retry-After": str(retry_after)}
    return SlackApiError("error", resp)


# ---------------------------------------------------------------------------
# fetch_channel_history
# ---------------------------------------------------------------------------


class TestFetchChannelHistory:
    @patch("slack_conversations.time.sleep")
    def test_single_page(self, mock_sleep):
        """1ページのみ（has_more=False）"""
        client = MagicMock()
        client.conversations_history.return_value = _make_history_response(
            [{"ts": "1.0", "text": "msg1"}], has_more=False
        )
        pages = list(fetch_channel_history(client, "C123"))
        assert len(pages) == 1
        assert pages[0] == [{"ts": "1.0", "text": "msg1"}]
        mock_sleep.assert_not_called()

    @patch("slack_conversations.time.sleep")
    def test_multi_page_with_cursor(self, mock_sleep):
        """has_more=True のときカーソルで次ページを取得する"""
        client = MagicMock()
        client.conversations_history.side_effect = [
            _make_history_response([{"ts": "1.0"}], has_more=True, next_cursor="cursor1"),
            _make_history_response([{"ts": "2.0"}], has_more=False),
        ]
        pages = list(fetch_channel_history(client, "C123"))
        assert len(pages) == 2
        assert pages[0] == [{"ts": "1.0"}]
        assert pages[1] == [{"ts": "2.0"}]
        # ページ間で Tier3 インターバルのスリープが入る
        mock_sleep.assert_called_once_with(1.5)
        # 2回目の呼び出しにカーソルが渡される
        second_call_kwargs = client.conversations_history.call_args_list[1][1]
        assert second_call_kwargs["cursor"] == "cursor1"

    @patch("slack_conversations.time.sleep")
    def test_three_pages_cursor_chained(self, mock_sleep):
        """3ページのカーソルチェーンが正しく動作する"""
        client = MagicMock()
        client.conversations_history.side_effect = [
            _make_history_response([{"ts": "1.0"}], has_more=True, next_cursor="c1"),
            _make_history_response([{"ts": "2.0"}], has_more=True, next_cursor="c2"),
            _make_history_response([{"ts": "3.0"}], has_more=False),
        ]
        pages = list(fetch_channel_history(client, "C123"))
        assert len(pages) == 3
        assert mock_sleep.call_count == 2
        calls = client.conversations_history.call_args_list
        assert "cursor" not in calls[0][1]
        assert calls[1][1]["cursor"] == "c1"
        assert calls[2][1]["cursor"] == "c2"

    @patch("slack_conversations.time.sleep")
    def test_empty_messages(self, mock_sleep):
        """空のメッセージリストでも正常に動作する"""
        client = MagicMock()
        client.conversations_history.return_value = _make_history_response([], has_more=False)
        pages = list(fetch_channel_history(client, "C123"))
        assert pages == [[]]
        mock_sleep.assert_not_called()

    @patch("slack_conversations.time.sleep")
    def test_ok_false_breaks_loop(self, mock_sleep):
        """ok=False のレスポンスでループを終了する"""
        client = MagicMock()
        resp = MagicMock()
        resp.get = lambda key, default=None: False if key == "ok" else default
        resp.__bool__ = lambda self: True
        client.conversations_history.return_value = resp
        pages = list(fetch_channel_history(client, "C123"))
        assert pages == []

    @patch("slack_conversations.time.sleep")
    def test_oldest_and_latest_params_passed(self, mock_sleep):
        """oldest / latest パラメータが API に渡される"""
        client = MagicMock()
        client.conversations_history.return_value = _make_history_response([])
        list(fetch_channel_history(client, "C123", oldest=1000.0, latest=2000.0))
        kwargs = client.conversations_history.call_args[1]
        assert kwargs["oldest"] == "1000.0"
        assert kwargs["latest"] == "2000.0"

    @patch("slack_rate_limit.time.sleep")
    def test_rate_limit_retry(self, mock_sleep):
        """レート制限エラー時にリトライして成功する"""
        client = MagicMock()
        client.conversations_history.side_effect = [
            _make_slack_error("ratelimited", status_code=429, retry_after=2),
            _make_slack_error("ratelimited", status_code=429, retry_after=2),
            _make_history_response([{"ts": "1.0"}], has_more=False),
        ]
        pages = list(fetch_channel_history(client, "C123"))
        assert len(pages) == 1
        assert pages[0] == [{"ts": "1.0"}]
        assert client.conversations_history.call_count == 3
        assert mock_sleep.call_count == 2


# ---------------------------------------------------------------------------
# fetch_all_channel_history
# ---------------------------------------------------------------------------


class TestFetchAllChannelHistory:
    @patch("slack_conversations.time.sleep")
    def test_flattens_multiple_pages(self, mock_sleep):
        """複数ページを1つのリストに結合する"""
        client = MagicMock()
        client.conversations_history.side_effect = [
            _make_history_response([{"ts": "1.0"}, {"ts": "2.0"}], has_more=True, next_cursor="c1"),
            _make_history_response([{"ts": "3.0"}], has_more=False),
        ]
        result = fetch_all_channel_history(client, "C123")
        assert result == [{"ts": "1.0"}, {"ts": "2.0"}, {"ts": "3.0"}]

    @patch("slack_conversations.time.sleep")
    def test_empty_result(self, mock_sleep):
        """空の結果を返す"""
        client = MagicMock()
        client.conversations_history.return_value = _make_history_response([])
        result = fetch_all_channel_history(client, "C123")
        assert result == []


# ---------------------------------------------------------------------------
# fetch_thread_replies
# ---------------------------------------------------------------------------


class TestFetchThreadReplies:
    @patch("slack_conversations.time.sleep")
    def test_skip_parent_true_removes_first_message(self, mock_sleep):
        """skip_parent=True のとき最初のメッセージ（親）を除外する"""
        client = MagicMock()
        client.conversations_replies.return_value = _make_history_response(
            [{"ts": "1.0", "text": "parent"}, {"ts": "1.1", "text": "reply1"}],
            has_more=False,
        )
        pages = list(fetch_thread_replies(client, "C123", "1.0", skip_parent=True))
        assert pages == [[{"ts": "1.1", "text": "reply1"}]]

    @patch("slack_conversations.time.sleep")
    def test_skip_parent_false_keeps_all(self, mock_sleep):
        """skip_parent=False のとき全メッセージを返す"""
        client = MagicMock()
        client.conversations_replies.return_value = _make_history_response(
            [{"ts": "1.0", "text": "parent"}, {"ts": "1.1", "text": "reply1"}],
            has_more=False,
        )
        pages = list(fetch_thread_replies(client, "C123", "1.0", skip_parent=False))
        assert pages == [[{"ts": "1.0", "text": "parent"}, {"ts": "1.1", "text": "reply1"}]]

    @patch("slack_conversations.time.sleep")
    def test_skip_parent_only_applies_to_first_page(self, mock_sleep):
        """skip_parent は1ページ目のみ適用され、2ページ目は全メッセージを返す"""
        client = MagicMock()
        client.conversations_replies.side_effect = [
            _make_history_response(
                [{"ts": "1.0", "text": "parent"}, {"ts": "1.1", "text": "reply1"}],
                has_more=True,
                next_cursor="c1",
            ),
            _make_history_response(
                [{"ts": "1.2", "text": "reply2"}, {"ts": "1.3", "text": "reply3"}],
                has_more=False,
            ),
        ]
        pages = list(fetch_thread_replies(client, "C123", "1.0", skip_parent=True))
        assert len(pages) == 2
        # 1ページ目: 親メッセージ除外
        assert pages[0] == [{"ts": "1.1", "text": "reply1"}]
        # 2ページ目: 除外なし
        assert pages[1] == [{"ts": "1.2", "text": "reply2"}, {"ts": "1.3", "text": "reply3"}]

    @patch("slack_conversations.time.sleep")
    def test_empty_first_page_sets_is_first_page_false(self, mock_sleep):
        """1ページ目が空でも is_first_page が False になり、2ページ目で親を除外しない"""
        client = MagicMock()
        client.conversations_replies.side_effect = [
            _make_history_response([], has_more=True, next_cursor="c1"),
            _make_history_response(
                [{"ts": "1.0", "text": "parent"}, {"ts": "1.1", "text": "reply1"}],
                has_more=False,
            ),
        ]
        pages = list(fetch_thread_replies(client, "C123", "1.0", skip_parent=True))
        assert len(pages) == 2
        assert pages[0] == []
        # 2ページ目では親を除外しない（is_first_page が正しく False になっている）
        assert pages[1] == [{"ts": "1.0", "text": "parent"}, {"ts": "1.1", "text": "reply1"}]

    @patch("slack_conversations.time.sleep")
    def test_multi_page_cursor_pagination(self, mock_sleep):
        """複数ページのカーソルページネーションが正しく動作する"""
        client = MagicMock()
        client.conversations_replies.side_effect = [
            _make_history_response([{"ts": "1.0"}, {"ts": "1.1"}], has_more=True, next_cursor="c1"),
            _make_history_response([{"ts": "1.2"}], has_more=True, next_cursor="c2"),
            _make_history_response([{"ts": "1.3"}], has_more=False),
        ]
        pages = list(fetch_thread_replies(client, "C123", "1.0", skip_parent=False))
        assert len(pages) == 3
        assert mock_sleep.call_count == 2
        calls = client.conversations_replies.call_args_list
        assert "cursor" not in calls[0][1]
        assert calls[1][1]["cursor"] == "c1"
        assert calls[2][1]["cursor"] == "c2"

    @patch("slack_conversations.time.sleep")
    def test_oldest_latest_and_ts_params_passed(self, mock_sleep):
        """ts / oldest / latest パラメータが API に渡される"""
        client = MagicMock()
        client.conversations_replies.return_value = _make_history_response([])
        list(fetch_thread_replies(client, "C123", "1.5", oldest=1000.0, latest=2000.0))
        kwargs = client.conversations_replies.call_args[1]
        assert kwargs["ts"] == "1.5"
        assert kwargs["oldest"] == "1000.0"
        assert kwargs["latest"] == "2000.0"

    @patch("slack_rate_limit.time.sleep")
    def test_rate_limit_retry(self, mock_sleep):
        """レート制限エラー時にリトライして成功する"""
        client = MagicMock()
        client.conversations_replies.side_effect = [
            _make_slack_error("ratelimited", status_code=429, retry_after=1),
            _make_history_response(
                [{"ts": "1.0", "text": "parent"}, {"ts": "1.1", "text": "reply"}],
                has_more=False,
            ),
        ]
        pages = list(fetch_thread_replies(client, "C123", "1.0", skip_parent=True))
        assert pages == [[{"ts": "1.1", "text": "reply"}]]
        assert client.conversations_replies.call_count == 2
        mock_sleep.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# fetch_all_thread_replies
# ---------------------------------------------------------------------------


class TestFetchAllThreadReplies:
    @patch("slack_conversations.time.sleep")
    def test_flattens_multiple_pages(self, mock_sleep):
        """複数ページを1つのリストに結合する"""
        client = MagicMock()
        client.conversations_replies.side_effect = [
            _make_history_response(
                [{"ts": "1.0"}, {"ts": "1.1"}, {"ts": "1.2"}], has_more=True, next_cursor="c1"
            ),
            _make_history_response([{"ts": "1.3"}], has_more=False),
        ]
        result = fetch_all_thread_replies(client, "C123", "1.0", skip_parent=True)
        # skip_parent=True: 1ページ目の先頭を除外 → [1.1, 1.2] + [1.3]
        assert result == [{"ts": "1.1"}, {"ts": "1.2"}, {"ts": "1.3"}]

    @patch("slack_conversations.time.sleep")
    def test_skip_parent_false_includes_all(self, mock_sleep):
        """skip_parent=False のとき全メッセージを含む"""
        client = MagicMock()
        client.conversations_replies.return_value = _make_history_response(
            [{"ts": "1.0"}, {"ts": "1.1"}], has_more=False
        )
        result = fetch_all_thread_replies(client, "C123", "1.0", skip_parent=False)
        assert result == [{"ts": "1.0"}, {"ts": "1.1"}]
