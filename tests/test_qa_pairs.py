"""Tests for qa_pairs module"""

from unittest.mock import MagicMock, patch

import pytest

from qa_pairs import (
    parse_arguments,
    classify_post,
    group_threads,
    format_message,
    build_pair,
    collect_qa_pairs,
    fetch_preceding,
)

PARENT = "https://x.slack.com/archives/C1/p100000001?thread_ts=100.000001&cid=C1"
REPLY = "https://x.slack.com/archives/C1/p200000002?thread_ts=100.000001&cid=C1"
TOP = "https://x.slack.com/archives/C1/p300000003"


def _match(ts, permalink, channel_id="C1"):
    return {"ts": ts, "permalink": permalink, "channel": {"id": channel_id, "name": "general"}}


# --- parse_arguments ---


class TestParseArguments:
    def test_subcommand_is_required(self):
        """サブコマンドなしはエラー"""
        with pytest.raises(SystemExit):
            parse_arguments([])

    def test_collect_rejects_days_with_after(self):
        """collect で --days と --after は同時に指定できない"""
        with pytest.raises(SystemExit):
            parse_arguments(["collect", "--user", "U1", "--days", "7", "--after", "2026-10-01"])

    def test_context_limit_defaults_to_20(self):
        """context の --limit は既定20"""
        args = parse_arguments(["context", "--targets", "t.json"])
        assert args.limit == 20


# --- classify_post ---


class TestClassifyPost:
    def test_reply_is_answerer(self):
        """スレッド返信は answerer"""
        assert classify_post(_match("200.000002", REPLY)) == ("answerer", "100.000001")

    def test_parent_is_asker(self):
        """スレッド親は asker"""
        assert classify_post(_match("100.000001", PARENT)) == ("asker", "100.000001")

    def test_top_level_is_standalone(self):
        """スレッドに属さない投稿は standalone"""
        assert classify_post(_match("300.000003", TOP)) == ("standalone", None)


# --- group_threads ---


class TestGroupThreads:
    def test_replies_in_same_thread_become_one_thread(self):
        """同じスレッドへの複数返信は1スレッドにまとめる"""
        threads, _ = group_threads([_match("200.000002", REPLY), _match("200.000003", REPLY)])
        assert len(threads) == 1

    def test_asker_wins_over_answerer(self):
        """本人が親なら、自分の返信があっても asker"""
        threads, _ = group_threads([_match("200.000002", REPLY), _match("100.000001", PARENT)])
        assert threads[0]["role"] == "asker"

    def test_same_thread_ts_in_other_channel_is_separate(self):
        """チャンネルが違えば別スレッド"""
        threads, _ = group_threads([_match("200.000002", REPLY, "C1"), _match("200.000002", REPLY, "C2")])
        assert len(threads) == 2

    def test_standalone_posts_are_separated(self):
        """スレッド外の投稿は別リストで返す"""
        threads, standalone = group_threads([_match("300.000003", TOP)])
        assert threads == [] and len(standalone) == 1


# --- format_message ---


class TestFormatMessage:
    def test_uses_jst_datetime_and_bot_fallback(self):
        """日時は JST。user がなければ bot_id を使う"""
        msg = {"ts": "1759885200.000100", "bot_id": "B1", "text": "hi"}
        assert format_message(msg) == {
            "ts": "1759885200.000100",
            "datetime": "2025-10-08 10:00:00",
            "user": "B1",
            "text": "hi",
        }


# --- build_pair ---


class TestBuildPair:
    def test_first_message_is_question_and_rest_are_answers(self):
        """先頭を question、残りを answers にし、本人の発言に印を付ける"""
        thread = {"role": "answerer", "channel_id": "C1", "channel_name": "general",
                  "thread_ts": "100.000001", "permalink": REPLY}
        messages = [
            {"ts": "100.000001", "user": "U2", "text": "q?"},
            {"ts": "200.000002", "user": "U1", "text": "a"},
            {"ts": "200.000003", "user": "U3", "text": "thx"},
        ]

        pair = build_pair(thread, messages, "U1")

        assert pair["source"] == "thread"
        assert pair["question"]["text"] == "q?"
        assert [a["is_target_user"] for a in pair["answers"]] == [True, False]


# --- collect_qa_pairs ---


class TestCollectQaPairs:
    @patch("qa_pairs.time.sleep")
    @patch("qa_pairs.fetch_thread")
    def test_skips_threads_that_could_not_be_fetched(self, mock_fetch, _sleep):
        """取得できなかったスレッドは結果に含めない"""
        mock_fetch.side_effect = [[], [{"ts": "100.000001", "user": "U2", "text": "q"}]]
        threads = [{"role": "answerer", "channel_id": "C1", "channel_name": "g",
                    "thread_ts": t, "permalink": None} for t in ("1.0", "100.000001")]

        pairs = collect_qa_pairs(MagicMock(), threads, "U1")

        assert len(pairs) == 1


# --- fetch_preceding ---


class TestFetchPreceding:
    @patch("qa_pairs.fetch_channel_history")
    def test_returns_messages_before_ts_oldest_first(self, mock_history):
        """指定 ts より前の最新 N 件を取り、古い順で返す"""
        mock_history.return_value = iter([[
            {"ts": "20.0", "user": "U2", "text": "newer"},
            {"ts": "10.0", "user": "U3", "text": "older"},
        ]])

        result = fetch_preceding(MagicMock(), "C1", "30.0", limit=2)

        assert [m["text"] for m in result] == ["older", "newer"]
        _, kwargs = mock_history.call_args
        assert kwargs["latest"] == "30.0" and kwargs["limit"] == 2
