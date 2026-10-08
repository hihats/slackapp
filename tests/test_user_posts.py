"""Tests for user_posts module"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from user_posts import (
    parse_arguments,
    resolve_date_range,
    build_user_query,
    fetch_user_posts,
    is_thread_reply,
    format_post,
)


# --- parse_arguments ---


class TestParseArguments:
    def test_days_and_after_cannot_be_combined(self):
        """--days と --after は同時に指定できない"""
        with pytest.raises(SystemExit):
            parse_arguments(["--user", "U123", "--days", "7", "--after", "2026-10-01"])

    def test_days_and_before_cannot_be_combined(self):
        """--days と --before は同時に指定できない"""
        with pytest.raises(SystemExit):
            parse_arguments(["--user", "U123", "--days", "7", "--before", "2026-10-01"])

    def test_after_is_parsed_as_date(self):
        """--after は日付として解釈される"""
        args = parse_arguments(["--user", "U123", "--after", "2026-10-01"])
        assert args.after == date(2026, 10, 1)


# --- resolve_date_range ---


class TestResolveDateRange:
    def test_defaults_to_30_days_when_nothing_given(self):
        """期間未指定なら30日前を after 境界にする"""
        after, before = resolve_date_range(None, None, None, today=date(2026, 10, 8))
        assert (after, before) == ("2026-09-08", None)

    def test_days_sets_only_after_boundary(self):
        """--days は after 境界だけを決める"""
        after, before = resolve_date_range(7, None, None, today=date(2026, 10, 8))
        assert (after, before) == ("2026-10-01", None)

    def test_explicit_dates_are_widened_to_include_both_ends(self):
        """--after/--before の指定日自体が範囲に含まれるよう1日ずつ外側にずらす"""
        after, before = resolve_date_range(
            None, date(2026, 10, 1), date(2026, 10, 5), today=date(2026, 10, 8)
        )
        assert (after, before) == ("2026-09-30", "2026-10-06")

    def test_after_only_leaves_before_open(self):
        """--after だけなら before 境界は付けない"""
        after, before = resolve_date_range(None, date(2026, 10, 1), None, today=date(2026, 10, 8))
        assert (after, before) == ("2026-09-30", None)


# --- build_user_query ---


class TestBuildUserQuery:
    def test_contains_from_modifier(self):
        """クエリに from:<@対象ユーザー> が入る"""
        query = build_user_query("U123", None, None, "2026-09-30", None)
        assert "from:<@U123>" in query
        assert "after:2026-09-30" in query

    def test_contains_all_filters_when_given(self):
        """channel・keyword・before を指定するとクエリに入る"""
        query = build_user_query("U123", "C789", "Deploy", "2026-09-30", "2026-10-06")
        assert "in:<#C789>" in query
        assert '"deploy"' in query
        assert "before:2026-10-06" in query

    def test_omits_before_when_not_given(self):
        """before 未指定ならクエリに before: を含めない"""
        query = build_user_query("U123", None, None, "2026-09-30", None)
        assert "before:" not in query


# --- fetch_user_posts ---


class TestFetchUserPosts:
    @patch("user_posts.search_all_messages")
    def test_removes_duplicates_by_channel_and_ts(self, mock_search):
        """同じ (channel, ts) のメッセージは1件にまとめる"""
        mock_search.return_value = [
            {"channel": {"id": "C1"}, "ts": "100.0"},
            {"channel": {"id": "C1"}, "ts": "100.0"},
            {"channel": {"id": "C2"}, "ts": "100.0"},
        ]

        posts = fetch_user_posts(MagicMock(), "from:<@U123>")

        assert len(posts) == 2


# --- is_thread_reply ---


class TestIsThreadReply:
    def test_top_level_post_is_not_reply(self):
        """permalink に thread_ts がない投稿は返信ではない"""
        match = {"ts": "100.000001", "permalink": "https://x.slack.com/archives/C1/p100000001"}
        assert is_thread_reply(match) is False

    def test_reply_has_different_thread_ts(self):
        """permalink の thread_ts が自身の ts と異なれば返信"""
        match = {
            "ts": "200.000002",
            "permalink": "https://x.slack.com/archives/C1/p200000002?thread_ts=100.000001&cid=C1",
        }
        assert is_thread_reply(match) is True

    def test_thread_parent_is_not_reply(self):
        """thread_ts が自身の ts と同じならスレッドの親で、返信ではない"""
        match = {
            "ts": "100.000001",
            "permalink": "https://x.slack.com/archives/C1/p100000001?thread_ts=100.000001&cid=C1",
        }
        assert is_thread_reply(match) is False

    def test_missing_permalink_is_not_reply(self):
        """permalink がなければ返信とは判定しない"""
        assert is_thread_reply({"ts": "100.000001"}) is False


# --- format_post ---


class TestFormatPost:
    def test_outputs_agreed_fields_with_jst_datetime(self):
        """合意した7項目を出力し、日時は JST で表す"""
        match = {
            "ts": "1759885200.000100",  # 2025-10-08 01:00:00 UTC
            "channel": {"id": "C1", "name": "general"},
            "text": "hello",
            "permalink": "https://x.slack.com/archives/C1/p1759885200000100",
        }

        post = format_post(match)

        assert post == {
            "ts": "1759885200.000100",
            "datetime": "2025-10-08 10:00:00",
            "channel_id": "C1",
            "channel_name": "general",
            "text": "hello",
            "permalink": "https://x.slack.com/archives/C1/p1759885200000100",
            "is_thread_reply": False,
        }
