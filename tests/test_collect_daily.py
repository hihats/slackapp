"""Tests for collect_daily module (Slack collector)"""

from datetime import date, datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from collect_daily import (
    resolve_date,
    in_target_day,
    output_filename,
    collect_slack,
)

JST = timezone(timedelta(hours=9))


# --- resolve_date ---


class TestResolveDate:
    def test_explicit_date_string_is_parsed(self):
        """YYYY-MM-DD 文字列はその日付として解釈される"""
        assert resolve_date("2026-06-19") == date(2026, 6, 19)

    @patch("collect_daily.datetime")
    def test_none_falls_back_to_jst_today(self, mock_dt):
        """未指定時は JST の当日になる"""
        mock_dt.now.return_value = datetime(2026, 6, 20, 0, 30, tzinfo=JST)
        assert resolve_date(None) == date(2026, 6, 20)


# --- in_target_day（JST境界） ---


class TestInTargetDay:
    def test_same_jst_day_is_included(self):
        """JST で同日なら対象に含む"""
        dt = datetime(2026, 6, 19, 9, 0, tzinfo=JST)
        assert in_target_day(dt, date(2026, 6, 19)) is True

    def test_utc_evening_crossing_into_next_jst_day_is_excluded(self):
        """UTC 6/19 15:30 は JST では 6/20 になり、6/19 対象からは外れる"""
        dt = datetime(2026, 6, 19, 15, 30, tzinfo=timezone.utc).astimezone(JST)
        assert in_target_day(dt, date(2026, 6, 19)) is False


# --- output_filename ---


class TestOutputFilename:
    def test_slack_source_writes_slack_json(self):
        """--source slack は <date>.slack.json に出力する"""
        assert output_filename("slack", date(2026, 6, 19)) == "2026-06-19.slack.json"


# --- collect_slack ---


class TestCollectSlack:
    @patch("collect_daily.search_all_messages")
    @patch("collect_daily.WebClient")
    def test_groups_messages_by_channel(self, mock_client_cls, mock_search):
        """検索結果を channel id 単位にグルーピングする"""
        client = MagicMock()
        client.auth_test.return_value = {"user_id": "U1"}
        mock_client_cls.return_value = client
        mock_search.return_value = [
            {"channel": {"id": "C1", "name": "general"}, "ts": "100.0",
             "text": "a", "permalink": "http://x/1"},
            {"channel": {"id": "C1", "name": "general"}, "ts": "101.0",
             "text": "b", "permalink": "http://x/2"},
            {"channel": {"id": "C2", "name": "random"}, "ts": "102.0",
             "text": "c", "permalink": "http://x/3"},
        ]

        result = collect_slack("xoxp-token", date(2026, 6, 19))

        assert result["user_id"] == "U1"
        channels = {c["id"]: c for c in result["channels"]}
        assert len(channels) == 2
        assert len(channels["C1"]["messages"]) == 2
        assert channels["C2"]["messages"][0]["text"] == "c"

    @patch("collect_daily.search_all_messages")
    @patch("collect_daily.WebClient")
    def test_query_uses_from_self_and_day_bounds(self, mock_client_cls, mock_search):
        """クエリは from:<@self> と前日/翌日の after:/before: 境界を含む"""
        client = MagicMock()
        client.auth_test.return_value = {"user_id": "U1"}
        mock_client_cls.return_value = client
        mock_search.return_value = []

        collect_slack("xoxp-token", date(2026, 6, 19))

        query = mock_search.call_args[0][1]
        assert "from:<@U1>" in query
        assert "after:2026-06-18" in query
        assert "before:2026-06-20" in query
