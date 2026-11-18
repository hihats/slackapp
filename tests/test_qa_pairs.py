"""Tests for qa_pairs module"""

from unittest.mock import MagicMock, patch

import pytest
from slack_sdk.errors import SlackApiError

from qa_pairs import (
    parse_arguments,
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


# --- group_threads ---


class TestGroupThreads:
    def test_replies_in_same_thread_become_one_thread(self):
        """同じスレッドへの複数返信は1スレッドにまとめる"""
        threads, _ = group_threads([_match("200.000002", REPLY), _match("200.000003", REPLY)])
        assert len(threads) == 1

    def test_parent_and_reply_in_same_thread_become_one_thread(self):
        """同じスレッドの親の投稿と返信は1スレッドにまとめる"""
        threads, _ = group_threads([_match("200.000002", REPLY), _match("100.000001", PARENT)])
        assert len(threads) == 1

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

    def test_app_message_with_user_and_bot_id_is_shown_as_bot(self):
        """user と bot_id の両方を持つアプリの投稿は bot_id で出す"""
        msg = {"ts": "1759885200.000100", "user": "U9", "bot_id": "B1", "text": "通知"}
        assert format_message(msg)["user"] == "B1"


# --- build_pair ---


class TestBuildPair:
    def test_first_message_is_question_and_rest_are_answers(self):
        """先頭を question、残りを answers にし、本人の発言に印を付ける"""
        thread = {"channel_id": "C1", "channel_name": "general",
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

    def test_thread_started_by_target_user_is_asker(self):
        """スレッドの親が本人なら、検索で親が見つかったかに関係なく asker"""
        thread = {"channel_id": "C1", "channel_name": "general",
                  "thread_ts": "100.000001", "permalink": REPLY}
        messages = [
            {"ts": "100.000001", "user": "U1", "text": "q?"},
            {"ts": "200.000002", "user": "U2", "text": "a"},
        ]

        assert build_pair(thread, messages, "U1")["role"] == "asker"

    def test_own_thread_found_only_by_reply_is_asker(self):
        """検索で本人の返信だけが見つかっても、親が本人なら asker"""
        threads, _ = group_threads([_match("200.000002", REPLY)])
        messages = [
            {"ts": "100.000001", "user": "U1", "text": "q?"},
            {"ts": "150.000001", "user": "U2", "text": "a"},
            {"ts": "200.000002", "user": "U1", "text": "thx"},
        ]

        assert build_pair(threads[0], messages, "U1")["role"] == "asker"

    def test_thread_started_by_others_is_answerer(self):
        """スレッドの親が他者なら answerer"""
        threads, _ = group_threads([_match("200.000002", REPLY)])
        messages = [
            {"ts": "100.000001", "user": "U2", "text": "q?"},
            {"ts": "200.000002", "user": "U1", "text": "a"},
        ]

        assert build_pair(threads[0], messages, "U1")["role"] == "answerer"


# --- collect_qa_pairs ---


def _thread(thread_ts):
    return {"channel_id": "C1", "channel_name": "g", "thread_ts": thread_ts, "permalink": None}


def _slack_error(error):
    # slack_sdk の WebClient は ok=False の応答を返さず SlackApiError を送出する
    return SlackApiError("The request to the Slack API failed.", response={"ok": False, "error": error})


@patch("slack_conversations.time.sleep")
@patch("qa_pairs.time.sleep")
class TestCollectQaPairs:
    def test_skips_threads_that_could_not_be_fetched(self, _sleep, _inner_sleep):
        """取得できなかったスレッドは結果に含めず、残りのスレッドは続けて取る"""
        client = MagicMock()
        client.conversations_replies.side_effect = [
            _slack_error("thread_not_found"),
            {"ok": True, "messages": [{"ts": "100.000001", "user": "U2", "text": "q"}]},
        ]

        pairs = collect_qa_pairs(client, [_thread("1.0"), _thread("100.000001")], "U1")

        assert len(pairs) == 1

    def test_stops_on_errors_not_specific_to_the_thread(self, _sleep, _inner_sleep):
        """認証などスレッド固有でないエラーでは止める"""
        client = MagicMock()
        client.conversations_replies.side_effect = _slack_error("invalid_auth")

        with pytest.raises(SlackApiError):
            collect_qa_pairs(client, [_thread("100.000001")], "U1")

    def test_thread_parent_becomes_question(self, _sleep, _inner_sleep):
        """スレッドの親を質問、返信を回答にする"""
        client = MagicMock()
        client.conversations_replies.return_value = {"ok": True, "messages": [
            {"ts": "100.000001", "user": "U2", "text": "q?"},
            {"ts": "200.000002", "user": "U1", "text": "a"},
        ]}

        pair, = collect_qa_pairs(client, [_thread("100.000001")], "U1")

        assert pair["question"]["text"] == "q?"
        assert [a["text"] for a in pair["answers"]] == ["a"]


# --- fetch_preceding ---


def _history(texts_newest_first, next_cursor=None, newest_ts=20):
    messages = [{"ts": f"{newest_ts - i}.0", "user": "U2", "text": t}
                for i, t in enumerate(texts_newest_first)]
    return {"ok": True, "messages": messages, "has_more": bool(next_cursor),
            "response_metadata": {"next_cursor": next_cursor or ""}}


@patch("slack_conversations.time.sleep")
class TestFetchPreceding:
    def test_returns_messages_before_ts_oldest_first(self, _sleep):
        """指定 ts より前の最新 N 件を取り、古い順で返す"""
        client = MagicMock()
        client.conversations_history.return_value = _history(["newer", "older"])

        result = fetch_preceding(client, "C1", "30.0", limit=2)

        assert [m["text"] for m in result] == ["older", "newer"]
        _, kwargs = client.conversations_history.call_args
        assert kwargs["latest"] == "30.0" and kwargs["limit"] == 2

    def test_fetches_next_page_until_limit_is_reached(self, _sleep):
        """1ページ目が limit に満たず続きがあれば、次のページも取る"""
        client = MagicMock()
        client.conversations_history.side_effect = [
            _history(["bot"], next_cursor="c2"),
            _history(["question", "older"], newest_ts=19),
        ]

        result = fetch_preceding(client, "C1", "30.0", limit=3)

        assert len(result) == 3 and result[-1]["text"] == "bot"

    def test_keeps_only_newest_limit_messages_across_pages(self, _sleep):
        """ページをまたいで limit を超えたら、新しい方から limit 件だけ返す"""
        client = MagicMock()
        client.conversations_history.side_effect = [
            _history(["newest"], next_cursor="c2"),
            _history(["second", "third", "fourth"], newest_ts=19),
        ]

        result = fetch_preceding(client, "C1", "30.0", limit=3)

        assert [m["text"] for m in result] == ["third", "second", "newest"]
