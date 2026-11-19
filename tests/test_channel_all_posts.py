"""Tests for channel_all_posts module"""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from slack_sdk.errors import SlackApiError

from channel_all_posts import collect_posts, parse_arguments, save_results, to_epoch_range

PARENT = {"ts": "100.000001", "thread_ts": "100.000001", "reply_count": 1, "text": "親", "user": "U1"}
REPLY = {"ts": "200.000002", "thread_ts": "100.000001", "text": "返信", "user": "U2"}
SINGLE = {"ts": "300.000003", "text": "単独", "user": "U1"}


def _page(messages):
    return {"ok": True, "messages": messages, "has_more": False}


def _slack_error(error):
    # slack_sdk の WebClient は ok=False の応答を返さず SlackApiError を送出する
    return SlackApiError("The request to the Slack API failed.", response={"ok": False, "error": error})


def _client(history, threads=None):
    """history: チャンネル直下の投稿（新しい順）。threads: 親の ts → 返信（親を除く）"""
    by_ts = {m["ts"]: m for m in history}
    client = MagicMock()
    client.conversations_history.return_value = _page(history)
    # conversations.replies は先頭に親を返す
    client.conversations_replies.side_effect = lambda **kw: _page([by_ts[kw["ts"]], *threads[kw["ts"]]])
    return client


@pytest.fixture(autouse=True)
def sleep():
    with patch("channel_all_posts.time.sleep") as mocked:
        yield mocked


class TestParseArguments:
    def test_channel_is_required(self):
        """--channel がなければエラーで終了する"""
        with pytest.raises(SystemExit):
            parse_arguments([])

    def test_period_is_unbounded_by_default(self):
        """期間を指定しなければ after / before は未設定になる"""
        args = parse_arguments(["--channel", "C123"])
        assert (args.after, args.before) == (None, None)

    def test_after_and_before_are_parsed_as_dates(self):
        """--after / --before は日付として解釈される"""
        args = parse_arguments(
            ["--channel", "C123", "--after", "2026-11-01", "--before", "2026-11-18"]
        )
        assert (args.after, args.before) == (date(2026, 11, 1), date(2026, 11, 18))


class TestToEpochRange:
    def test_no_dates_means_no_bounds(self):
        """日付がなければ境界もない（全期間）"""
        assert to_epoch_range(None, None) == (None, None)

    def test_after_starts_at_jst_midnight_of_that_day(self):
        """--after の日は JST 0時から含まれる"""
        oldest, _ = to_epoch_range(date(2026, 11, 1), None)
        assert oldest == 1793458800  # 2026-11-01 00:00:00 JST

    def test_before_ends_at_jst_midnight_of_next_day(self):
        """--before の日は JST で翌日0時の直前まで含まれる"""
        _, latest = to_epoch_range(None, date(2026, 11, 18))
        assert latest == 1795014000  # 2026-11-19 00:00:00 JST


class TestCollectPosts:
    def test_whole_history_is_requested_when_no_bounds(self):
        """境界を渡さなければ oldest / latest を付けずに履歴を取る"""
        client = _client([SINGLE])
        collect_posts(client, "C1")
        kwargs = client.conversations_history.call_args[1]
        assert "oldest" not in kwargs and "latest" not in kwargs

    def test_bounds_are_passed_to_history(self):
        """境界を渡せばその範囲で履歴を取る"""
        client = _client([SINGLE])
        collect_posts(client, "C1", oldest=1793458800.0, latest=1795014000.0)
        kwargs = client.conversations_history.call_args[1]
        assert (float(kwargs["oldest"]), float(kwargs["latest"])) == (1793458800.0, 1795014000.0)

    def test_replies_are_collected_with_their_parent(self):
        """スレッドの返信も親と合わせて集める"""
        posts, _ = collect_posts(_client([PARENT], {PARENT["ts"]: [REPLY]}), "C1")
        assert [p["text"] for p in posts] == ["親", "返信"]

    def test_threads_are_fetched_only_for_posts_with_replies(self):
        """返信のない投稿についてはスレッドを取りに行かない"""
        client = _client([SINGLE, PARENT], {PARENT["ts"]: [REPLY]})
        collect_posts(client, "C1")
        assert [c[1]["ts"] for c in client.conversations_replies.call_args_list] == [PARENT["ts"]]

    def test_waits_between_thread_fetches(self, sleep):
        """スレッドを続けて取るときは間に 1.5 秒待つ"""
        second = {**PARENT, "ts": "150.000001", "thread_ts": "150.000001"}
        collect_posts(_client([second, PARENT], {PARENT["ts"]: [], second["ts"]: []}), "C1")
        sleep.assert_called_once_with(1.5)

    def test_reply_also_sent_to_channel_appears_once(self):
        """チャンネルにも投稿された返信が履歴とスレッドの両方にあっても 1 件になる"""
        broadcast = {**REPLY, "subtype": "thread_broadcast"}
        posts, _ = collect_posts(_client([broadcast, PARENT], {PARENT["ts"]: [broadcast]}), "C1")
        assert [p["ts"] for p in posts] == [PARENT["ts"], REPLY["ts"]]

    def test_posts_are_ordered_oldest_first(self):
        """投稿は古い順に並ぶ"""
        posts, _ = collect_posts(_client([SINGLE, PARENT], {PARENT["ts"]: [REPLY]}), "C1")
        assert [p["ts"] for p in posts] == ["100.000001", "200.000002", "300.000003"]

    def test_only_agreed_keys_are_kept(self):
        """出力に残すのは決めたキーだけ（投稿者やリアクションは残さない）"""
        noisy = {**SINGLE, "user_profile": {"real_name": "hihats"}, "reactions": [{"name": "eyes", "users": ["U9"]}]}
        posts, _ = collect_posts(_client([noisy]), "C1")
        assert set(posts[0]) == {"ts", "datetime", "thread_ts", "is_thread_reply", "subtype",
                                 "text", "attachments", "blocks", "files"}

    def test_body_fields_are_kept_as_returned(self):
        """text / attachments / blocks / files は Slack が返した形のまま残す"""
        body = {"text": "",
                "attachments": [{"text": "添付の本文"}],
                "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "ブロックの本文"}}],
                "files": [{"id": "F1", "name": "list.xlsx", "url_private": "https://files.slack.com/F1"}]}
        posts, _ = collect_posts(_client([{"ts": "400.000004", "subtype": "bot_message", **body}]), "C1")
        assert {k: posts[0][k] for k in body} == body

    def test_only_replies_are_marked_as_thread_replies(self):
        """返信だけが is_thread_reply になる（親と単独の投稿はならない）"""
        posts, _ = collect_posts(_client([SINGLE, PARENT], {PARENT["ts"]: [REPLY]}), "C1")
        assert {p["text"]: p["is_thread_reply"] for p in posts} == {"親": False, "返信": True, "単独": False}

    def test_datetime_is_shown_in_jst(self):
        """datetime は JST で表す"""
        posts, _ = collect_posts(_client([{"ts": "1793458800.000000", "text": "x"}]), "C1")
        assert posts[0]["datetime"] == "2026-11-01 00:00:00"

    def test_missing_thread_is_skipped_and_reported(self):
        """見つからないスレッドは飛ばし、その ts を返す"""
        client = _client([PARENT])
        client.conversations_replies.side_effect = _slack_error("thread_not_found")
        posts, skipped = collect_posts(client, "C1")
        assert ([p["ts"] for p in posts], skipped) == ([PARENT["ts"]], [PARENT["ts"]])

    def test_other_api_errors_abort(self):
        """それ以外の API エラーは中断する"""
        client = _client([PARENT])
        client.conversations_replies.side_effect = _slack_error("invalid_auth")
        with pytest.raises(SlackApiError):
            collect_posts(client, "C1")


class TestSaveResults:
    def test_missing_output_directory_is_created(self, tmp_path):
        """出力先のディレクトリがなければ作って保存する"""
        path = tmp_path / "outputs" / "posts.json"
        save_results({"count": 0, "messages": []}, path)
        assert json.loads(path.read_text(encoding="utf-8")) == {"count": 0, "messages": []}

    def test_japanese_is_written_unescaped(self, tmp_path):
        """日本語はエスケープせずに書く（保存したファイルをそのまま検索できる）"""
        path = tmp_path / "posts.json"
        save_results({"messages": [{"text": "住所は東京都"}]}, path)
        assert "住所は東京都" in path.read_text(encoding="utf-8")
