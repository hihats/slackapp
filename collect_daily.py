"""
当日の業務データ収集スクリプト（Phase 1）

Slack（当日自分が投稿したチャンネル/DM）と Claude セッション履歴
（Claude Code + Cowork メタデータ）を JST 当日基準で収集し、
要約用の中間 JSON (outputs/daily/<date>.raw.json) を出力する。

要約・整形・Slack投稿は呼び出し側（/daily-report スキル）が担当する。
"""

import argparse
import glob
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from slack_sdk import WebClient

from slack_search import search_all_messages

JST = timezone(timedelta(hours=9))

# Cowork セッションメタデータの探索ルート
COWORK_ROOT = Path.home() / "Library/Application Support/Claude/local-agent-mode-sessions"
# Claude Code トランスクリプトの探索ルート
CLAUDE_CODE_ROOT = Path.home() / ".claude/projects"

# 出力に載せない PII フィールド（組織方針）
PII_FIELDS = {"emailAddress", "accountName"}


def parse_arguments():
    parser = argparse.ArgumentParser(description="当日の業務データを収集して中間JSONを出力する")
    parser.add_argument("--date", type=str, help="対象日 YYYY-MM-DD（省略時はJST当日）")
    parser.add_argument("--token", type=str, default=os.environ.get("SLACK_TOKEN"),
                        help="Slackユーザートークン（search:read 必須／既定は環境変数 SLACK_TOKEN）")
    parser.add_argument("--output-dir", type=str, default="outputs/daily", help="出力先ディレクトリ")
    parser.add_argument("--source", choices=["all", "slack", "claude"], default="all",
                        help="収集対象。slack=Slack(Docker実行想定) / claude=Claude履歴(ホスト実行想定) / all=両方")
    return parser.parse_args()


def resolve_date(date_str):
    """対象日を date 型で返す。未指定なら JST 当日。"""
    if date_str:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    return datetime.now(JST).date()


# --source ごとに部分収集結果を別ファイルに分けることで、
# Slack(Docker) と Claude履歴(ホスト) を別プロセスで収集し後段でマージできる
_SOURCE_SUFFIX = {"all": "raw", "slack": "slack", "claude": "claude"}


def output_filename(source, target):
    """--source と対象日から中間JSONのファイル名を決める。"""
    return f"{target.isoformat()}.{_SOURCE_SUFFIX[source]}.json"


def in_target_day(dt_jst, target):
    """JST に変換済みの datetime が対象日かどうか。"""
    return dt_jst.date() == target


def collect_slack(token, target):
    """当日自分が投稿したチャンネル/DM を search.messages で収集しグルーピングする。"""
    client = WebClient(token=token)
    user_id = client.auth_test()["user_id"]

    # search.messages は after:/before: 排他境界。前日〜翌日で当日を挟む
    after = (target - timedelta(days=1)).isoformat()
    before = (target + timedelta(days=1)).isoformat()
    query = f"from:<@{user_id}> after:{after} before:{before}"

    matches = search_all_messages(client, query)

    channels = {}
    for m in matches:
        ch = m.get("channel", {}) or {}
        cid = ch.get("id", "unknown")
        bucket = channels.setdefault(cid, {
            "id": cid,
            "name": ch.get("name") or ch.get("user") or cid,
            "is_im": ch.get("is_im", False) or ch.get("is_mpim", False),
            "messages": [],
        })
        bucket["messages"].append({
            "ts": m.get("ts"),
            "text": m.get("text", ""),
            "permalink": m.get("permalink"),
        })
    return {"user_id": user_id, "channels": list(channels.values())}


def _user_prompt_text(o):
    """type:user 行が実プロンプト(文字列)ならその本文を、そうでなければ None を返す。

    content が list の行(tool_result 等)や isMeta 行はユーザーの入力ではないため除外する。
    """
    if o.get("type") != "user" or o.get("isMeta"):
        return None
    content = (o.get("message") or {}).get("content")
    return content if isinstance(content, str) else None


def collect_claude_code(target):
    """Claude Code トランスクリプト(*.jsonl)から当日分をセッション単位に集約する。

    ai-title 行は timestamp を持たないため、日付に依らず sessionId 単位で先に集める。
    当日のタイムスタンプを持つ行があったセッションのみを結果に含め、title を後付けする。
    """
    sessions = {}   # 当日活動のあったセッション
    titles = {}     # sessionId -> aiTitle（timestamp 非依存で収集）
    for path in glob.glob(str(CLAUDE_CODE_ROOT / "*/*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if o.get("type") == "ai-title" and o.get("aiTitle"):
                    titles[o.get("sessionId")] = o["aiTitle"]
                    continue

                ts = o.get("timestamp")
                if not ts:
                    continue
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(JST)
                if not in_target_day(dt, target):
                    continue

                sid = o.get("sessionId", path)
                s = sessions.setdefault(sid, {
                    "session_id": sid,
                    "cwd": o.get("cwd"),
                    "git_branch": o.get("gitBranch"),
                    "title": None,
                    "prompts": [],
                })
                if o.get("cwd"):
                    s["cwd"] = o["cwd"]
                if o.get("gitBranch"):
                    s["git_branch"] = o["gitBranch"]

                prompt = _user_prompt_text(o)
                if prompt:
                    s["prompts"].append(prompt)

    for sid, s in sessions.items():
        s["title"] = titles.get(sid)
    return list(sessions.values())


def collect_cowork(target):
    """Cowork セッションメタデータ(local_*.json)から当日分を抽出する（PIIは除外）。"""
    results = []
    for path in glob.glob(str(COWORK_ROOT / "**/local_*.json"), recursive=True):
        if "backup" in path:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                o = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        epoch_ms = o.get("createdAt") or o.get("lastActivityAt")
        if not epoch_ms:
            continue
        dt = datetime.fromtimestamp(epoch_ms / 1000, JST)
        if not in_target_day(dt, target):
            continue
        results.append({
            "title": o.get("title"),
            "initial_message": o.get("initialMessage"),
            "cwd": o.get("cwd"),
            "model": o.get("model"),
            "created_at": dt.isoformat(),
            "session_type": o.get("sessionType"),
        })
        # PII_FIELDS は意図的に取り込まない（組織方針）
    return results


def main():
    args = parse_arguments()
    target = resolve_date(args.date)

    data = {"date": target.isoformat()}

    if args.source in ("all", "slack"):
        if not args.token:
            raise SystemExit("Slackトークンが未指定です（--token または環境変数 SLACK_TOKEN）")
        data["slack"] = collect_slack(args.token, target)

    if args.source in ("all", "claude"):
        data["claude_code"] = collect_claude_code(target)
        data["cowork"] = collect_cowork(target)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / output_filename(args.source, target)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"収集完了: {out_path}")
    if "slack" in data:
        print(f"  Slack: {len(data['slack']['channels'])} チャンネル/DM")
    if "claude_code" in data:
        print(f"  Claude Code: {len(data['claude_code'])} セッション")
        print(f"  Cowork: {len(data['cowork'])} セッション")


if __name__ == "__main__":
    main()
