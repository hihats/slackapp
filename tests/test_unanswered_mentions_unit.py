"""Unit tests for unanswered_mentions module"""

import time
from unittest.mock import MagicMock, patch

from unanswered_mentions import (
    check_user_reactions_and_replies,
    format_message_data,
    get_messages_with_mentions,
)


def _thread(*messages):
    return [{"ts": ts, "user": user, "text": "t"} for ts, user in messages]


# --- check_user_reactions_and_replies ---


@patch("unanswered_mentions.fetch_channel_history", return_value=[])
@patch("unanswered_mentions.fetch_all_thread_replies")
class TestCheckUserReactionsAndReplies:
    def test_reply_only_before_mention_is_unanswered(self, replies, _history):
        """メンションより前にだけ本人の返信があるスレッドは未回答"""
        replies.return_value = _thread(("100.0", "U2"), ("150.0", "U1"), ("200.0", "U2"))
        mention = {"ts": "200.0", "thread_ts": "100.0", "user": "U2", "text": "<@U1> 教えて"}

        answered, _, _ = check_user_reactions_and_replies(MagicMock(), "C1", mention, "U1")

        assert answered is False

    def test_reply_after_mention_is_answered(self, replies, _history):
        """メンションより後に本人の返信があれば回答済み"""
        replies.return_value = _thread(("100.0", "U2"), ("200.0", "U2"), ("250.0", "U1"))
        mention = {"ts": "200.0", "thread_ts": "100.0", "user": "U2", "text": "<@U1> 教えて"}

        answered, kind, _ = check_user_reactions_and_replies(MagicMock(), "C1", mention, "U1")

        assert (answered, kind) == (True, "reply")


# --- format_message_data ---


class TestFormatMessageData:
    def test_thread_reply_has_thread_ts(self):
        """スレッド内の投稿は thread_ts を出す"""
        message = {"ts": "200.0", "thread_ts": "100.0", "user": "U2", "text": "<@U1> 教えて"}

        data = format_message_data(message, "C1", "#general", None, None)

        assert data["thread_ts"] == "100.0"


# --- get_messages_with_mentions ---


def _ts(days_ago):
    return f"{time.time() - days_ago * 86400:.6f}"


def _slack(thread, matches):
    """期間内に親がないチャンネルと、検索結果・スレッドを返す偽の Slack クライアント"""
    client = MagicMock()
    client.conversations_history.return_value = {"ok": True, "messages": []}
    client.search_messages.return_value = {
        "ok": True,
        "messages": {"matches": matches, "pagination": {"page": 1, "page_count": 1}},
    }
    client.conversations_replies.return_value = {"ok": True, "messages": thread}
    return client


class TestGetMessagesWithMentions:
    def test_mention_in_thread_started_before_period_is_returned(self):
        """期間より前に始まったスレッドの中の、期間内のメンションも返す"""
        parent_ts, mention_ts = _ts(days_ago=100), _ts(days_ago=1)
        thread = [
            {"ts": parent_ts, "user": "U2", "text": "相談です", "reply_count": 1},
            {"ts": mention_ts, "thread_ts": parent_ts, "user": "U2", "text": "<@U1> 教えて"},
        ]
        permalink = ("https://example.slack.com/archives/C1/p"
                     f"{mention_ts.replace('.', '')}?thread_ts={parent_ts}")
        client = _slack(thread, [{"ts": mention_ts, "permalink": permalink}])

        messages = get_messages_with_mentions(client, "C1", "U1", 7)

        assert [m["ts"] for m in messages] == [mention_ts]
        assert messages[0]["thread_ts"] == parent_ts

    def test_mention_before_period_is_not_returned(self):
        """検索に入っても、期間より前のメンションは返さない"""
        old_ts = _ts(days_ago=7.5)
        message = {"ts": old_ts, "user": "U2", "text": "<@U1> 教えて"}
        permalink = f"https://example.slack.com/archives/C1/p{old_ts.replace('.', '')}"
        client = _slack([message], [{"ts": old_ts, "permalink": permalink}])

        messages = get_messages_with_mentions(client, "C1", "U1", 7)

        assert messages == []
