"""Unit tests for unanswered_mentions module"""

from unittest.mock import MagicMock, patch

from unanswered_mentions import check_user_reactions_and_replies, format_message_data


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
