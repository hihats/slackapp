"""Tests for collect_daily module"""

import json
from datetime import date, datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from collect_daily import (
    resolve_date,
    in_target_day,
    output_filename,
    collect_slack,
    collect_claude_code,
    collect_cowork,
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


# --- output_filename（--source ごとの出力ファイル名） ---


class TestOutputFilename:
    def test_slack_source_writes_slack_json(self):
        """--source slack は <date>.slack.json に出力する（Docker実行分）"""
        assert output_filename("slack", date(2026, 6, 19)) == "2026-06-19.slack.json"

    def test_claude_source_writes_claude_json(self):
        """--source claude は <date>.claude.json に出力する（ホスト実行分）"""
        assert output_filename("claude", date(2026, 6, 19)) == "2026-06-19.claude.json"

    def test_all_source_keeps_raw_json_for_compat(self):
        """--source all は従来どおり <date>.raw.json（後方互換）"""
        assert output_filename("all", date(2026, 6, 19)) == "2026-06-19.raw.json"


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


# --- collect_claude_code ---


class TestCollectClaudeCode:
    def _write_jsonl(self, tmp_path, lines):
        proj = tmp_path / "proj"
        proj.mkdir()
        f = proj / "session.jsonl"
        f.write_text("\n".join(json.dumps(o) for o in lines), encoding="utf-8")
        return tmp_path

    def _user(self, session_id, content, ts, **extra):
        """実データ準拠の type:user 行を生成する"""
        line = {"type": "user", "sessionId": session_id, "timestamp": ts,
                "message": {"role": "user", "content": content}}
        line.update(extra)
        return line

    def test_title_comes_from_untimestamped_ai_title_line(self, tmp_path, monkeypatch):
        """ai-title 行は timestamp を持たないが、当日活動セッションに title として紐付く"""
        root = self._write_jsonl(tmp_path, [
            {"type": "ai-title", "sessionId": "s1", "aiTitle": "Refactor X"},
            self._user("s1", "本文プロンプト", "2026-06-19T02:00:00.000Z",
                       cwd="/repo", gitBranch="main"),
        ])
        monkeypatch.setattr("collect_daily.CLAUDE_CODE_ROOT", root)

        result = collect_claude_code(date(2026, 6, 19))

        assert len(result) == 1
        s = result[0]
        assert s["title"] == "Refactor X"
        assert s["cwd"] == "/repo"
        assert s["git_branch"] == "main"

    def test_prompts_come_from_user_string_content_of_target_day(self, tmp_path, monkeypatch):
        """type:user の content(文字列)を当日分のみ prompts に集約する"""
        root = self._write_jsonl(tmp_path, [
            self._user("s1", "当日のプロンプト", "2026-06-19T02:00:00.000Z", cwd="/repo"),
            self._user("s1", "別日のプロンプト", "2026-06-10T02:00:00.000Z", cwd="/repo"),
        ])
        monkeypatch.setattr("collect_daily.CLAUDE_CODE_ROOT", root)

        result = collect_claude_code(date(2026, 6, 19))

        assert result[0]["prompts"] == ["当日のプロンプト"]

    def test_tool_result_and_meta_user_lines_are_not_prompts(self, tmp_path, monkeypatch):
        """content が list(tool_result) の行や isMeta 行は prompts に含めない"""
        root = self._write_jsonl(tmp_path, [
            self._user("s1", "実プロンプト", "2026-06-19T02:00:00.000Z", cwd="/repo"),
            self._user("s1", [{"type": "tool_result", "content": "x"}],
                       "2026-06-19T02:05:00.000Z", cwd="/repo"),
            self._user("s1", "メタ扱い", "2026-06-19T02:10:00.000Z", cwd="/repo", isMeta=True),
        ])
        monkeypatch.setattr("collect_daily.CLAUDE_CODE_ROOT", root)

        result = collect_claude_code(date(2026, 6, 19))

        assert result[0]["prompts"] == ["実プロンプト"]

    def test_session_without_target_day_activity_is_excluded(self, tmp_path, monkeypatch):
        """当日活動が無いセッションは、ai-title があっても結果に含めない"""
        root = self._write_jsonl(tmp_path, [
            {"type": "ai-title", "sessionId": "s9", "aiTitle": "別日のセッション"},
            self._user("s9", "別日のみ", "2026-06-10T02:00:00.000Z", cwd="/repo"),
        ])
        monkeypatch.setattr("collect_daily.CLAUDE_CODE_ROOT", root)

        assert collect_claude_code(date(2026, 6, 19)) == []


# --- collect_cowork ---


class TestCollectCowork:
    def _write_session(self, tmp_path, name, obj):
        d = tmp_path / "install" / "account"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(json.dumps(obj), encoding="utf-8")
        return tmp_path

    def test_collects_target_day_by_epoch_ms(self, tmp_path, monkeypatch):
        """createdAt(epochミリ秒) が JST 対象日のセッションを拾う"""
        # 2026-06-19 10:00 JST
        ms = int(datetime(2026, 6, 19, 10, 0, tzinfo=JST).timestamp() * 1000)
        root = self._write_session(tmp_path, "local_a.json", {
            "title": "Weekly report", "initialMessage": "make report",
            "cwd": "/w", "model": "claude", "createdAt": ms,
        })
        monkeypatch.setattr("collect_daily.COWORK_ROOT", root)

        result = collect_cowork(date(2026, 6, 19))

        assert len(result) == 1
        assert result[0]["title"] == "Weekly report"

    def test_excludes_pii_fields(self, tmp_path, monkeypatch):
        """emailAddress / accountName は出力に含めない（組織方針）"""
        ms = int(datetime(2026, 6, 19, 10, 0, tzinfo=JST).timestamp() * 1000)
        root = self._write_session(tmp_path, "local_b.json", {
            "title": "T", "createdAt": ms,
            "emailAddress": "x@example.com", "accountName": "Someone",
        })
        monkeypatch.setattr("collect_daily.COWORK_ROOT", root)

        result = collect_cowork(date(2026, 6, 19))

        assert "emailAddress" not in result[0]
        assert "accountName" not in result[0]

    def test_backup_files_are_skipped(self, tmp_path, monkeypatch):
        """backup ファイルは収集対象外"""
        ms = int(datetime(2026, 6, 19, 10, 0, tzinfo=JST).timestamp() * 1000)
        root = self._write_session(tmp_path, "local_c.json.backup.123", {
            "title": "B", "createdAt": ms,
        })
        monkeypatch.setattr("collect_daily.COWORK_ROOT", root)

        assert collect_cowork(date(2026, 6, 19)) == []
