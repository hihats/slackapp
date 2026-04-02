"""Tests for inactive_channels module"""

import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from slack_sdk.errors import SlackApiError

from inactive_channels import (
    check_inactive_channels,
    get_channel_last_message_time,
    load_channels_from_json,
    save_results_to_json,
)


# --- load_channels_from_json ---


class TestLoadChannelsFromJson:
    def test_filters_public_and_private_channels(self, tmp_path):
        """パブリック・プライベートチャンネルのみ返し、DM/グループDMは除外"""
        data = {
            "channels": [
                {"id": "C1", "name": "general", "is_channel": True, "is_im": False, "is_mpim": False},
                {"id": "C2", "name": "private", "is_group": True, "is_im": False, "is_mpim": False},
                {"id": "D1", "name": "dm", "is_channel": False, "is_im": True, "is_mpim": False},
                {"id": "G1", "name": "group_dm", "is_channel": False, "is_im": False, "is_mpim": True},
            ]
        }
        json_path = tmp_path / "channels.json"
        json_path.write_text(json.dumps(data), encoding="utf-8")

        result = load_channels_from_json(str(json_path))

        assert len(result) == 2
        assert result[0]["id"] == "C1"
        assert result[1]["id"] == "C2"

    def test_file_not_found_returns_empty(self, tmp_path):
        """存在しないファイルを指定すると空リスト"""
        result = load_channels_from_json(str(tmp_path / "nonexistent.json"))
        assert result == []

    def test_invalid_json_returns_empty(self, tmp_path):
        """不正なJSONファイルは空リスト"""
        json_path = tmp_path / "bad.json"
        json_path.write_text("{invalid", encoding="utf-8")

        result = load_channels_from_json(str(json_path))
        assert result == []


# --- get_channel_last_message_time ---


class TestGetChannelLastMessageTime:
    def _make_response(self, messages):
        resp = MagicMock()
        data = {"ok": True, "messages": messages}
        resp.__getitem__ = lambda self, key: data[key]
        resp.__bool__ = lambda self: True
        resp.get = lambda key, default=None: data.get(key, default)
        return resp

    @patch("inactive_channels.handle_rate_limit")
    def test_returns_datetime_of_latest_message(self, mock_hrl):
        """最新メッセージのタイムスタンプを datetime で返す"""
        ts = "1700000000.000000"
        mock_hrl.return_value = self._make_response([{"ts": ts}])
        client = MagicMock()

        result = get_channel_last_message_time(client, "C123")

        assert isinstance(result, datetime)
        assert result == datetime.fromtimestamp(1700000000.0, tz=timezone.utc)

    @patch("inactive_channels.handle_rate_limit")
    def test_no_messages_returns_none(self, mock_hrl):
        """メッセージが空の場合は None"""
        mock_hrl.return_value = self._make_response([])
        client = MagicMock()

        assert get_channel_last_message_time(client, "C123") is None

    @patch("inactive_channels.handle_rate_limit")
    def test_channel_not_found_returns_none(self, mock_hrl):
        """channel_not_found エラーで None"""
        error_resp = MagicMock()
        error_resp.__getitem__ = lambda self, key: "channel_not_found" if key == "error" else None
        mock_hrl.side_effect = SlackApiError("not found", response=error_resp)
        client = MagicMock()

        assert get_channel_last_message_time(client, "C123") is None

    @patch("inactive_channels.handle_rate_limit")
    def test_not_in_channel_returns_none(self, mock_hrl):
        """not_in_channel エラーで None"""
        error_resp = MagicMock()
        error_resp.__getitem__ = lambda self, key: "not_in_channel" if key == "error" else None
        mock_hrl.side_effect = SlackApiError("no access", response=error_resp)
        client = MagicMock()

        assert get_channel_last_message_time(client, "C123") is None


# --- check_inactive_channels ---


class TestCheckInactiveChannels:
    @patch("inactive_channels.time.sleep")
    @patch("inactive_channels.get_channel_last_message_time")
    def test_only_inactive_channels_returned(self, mock_get_time, mock_sleep):
        """閾値より古いチャンネルのみ非アクティブとして返す"""
        now = datetime.now(timezone.utc)
        old_date = now - timedelta(days=400)
        recent_date = now - timedelta(days=30)

        mock_get_time.side_effect = [old_date, recent_date]

        channels = [
            {"id": "C1", "name": "old_channel"},
            {"id": "C2", "name": "active_channel"},
        ]
        client = MagicMock()

        result = check_inactive_channels(client, channels)

        assert len(result) == 1
        assert result[0]["id"] == "C1"
        assert result[0]["days_since_last_post"] >= 400

    @patch("inactive_channels.time.sleep")
    @patch("inactive_channels.get_channel_last_message_time")
    def test_skips_channels_with_no_messages(self, mock_get_time, mock_sleep):
        """メッセージ取得できないチャンネルはスキップ"""
        now = datetime.now(timezone.utc)
        old_date = now - timedelta(days=500)

        mock_get_time.side_effect = [None, old_date]

        channels = [
            {"id": "C1", "name": "no_messages"},
            {"id": "C2", "name": "old_channel"},
        ]
        client = MagicMock()

        result = check_inactive_channels(client, channels)

        assert len(result) == 1
        assert result[0]["id"] == "C2"


# --- save_results_to_json ---


class TestSaveResultsToJson:
    def test_sorted_by_days_since_last_post_descending(self, tmp_path):
        """days_since_last_post の降順でソートされる"""
        inactive = [
            {"name": "a", "days_since_last_post": 100, "last_message_time": "2024-01-01"},
            {"name": "b", "days_since_last_post": 500, "last_message_time": "2023-01-01"},
            {"name": "c", "days_since_last_post": 300, "last_message_time": "2023-06-01"},
        ]
        output_path = str(tmp_path / "result.json")

        save_results_to_json(inactive, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        channels = data["inactive_channels"]
        assert channels[0]["days_since_last_post"] == 500
        assert channels[1]["days_since_last_post"] == 300
        assert channels[2]["days_since_last_post"] == 100

    def test_output_json_structure(self, tmp_path):
        """出力JSONの構造が正しい"""
        inactive = [
            {"name": "a", "days_since_last_post": 400, "last_message_time": "2024-01-01"},
        ]
        output_path = str(tmp_path / "result.json")

        save_results_to_json(inactive, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "analysis_date" in data
        assert data["threshold_days"] == 365
        assert data["total_inactive_channels"] == 1
        assert len(data["inactive_channels"]) == 1
