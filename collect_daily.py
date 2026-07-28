"""
当日の Slack 投稿収集スクリプト

当日自分が投稿したチャンネル/DM を search.messages で収集し、
要約用の中間 JSON (<output-dir>/<date>.slack.json) を出力する。

Claude履歴・GitHub・カレンダー等のローカル資産の収集と、要約・投稿の
オーケストレーションは action_report リポジトリの責務。
"""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from slack_sdk import WebClient

from slack_search import search_all_messages

JST = timezone(timedelta(hours=9))


def parse_arguments():
    parser = argparse.ArgumentParser(description="当日自分が投稿したSlackメッセージを収集して中間JSONを出力する")
    parser.add_argument("--date", type=str, help="対象日 YYYY-MM-DD（省略時はJST当日）")
    parser.add_argument("--token", type=str, default=os.environ.get("SLACK_TOKEN"),
                        help="Slackユーザートークン（search:read 必須／既定は環境変数 SLACK_TOKEN）")
    parser.add_argument("--output-dir", type=str, default="outputs/daily", help="出力先ディレクトリ")
    parser.add_argument("--source", choices=["slack"], default="slack",
                        help="収集対象（互換性のため残置。slack のみ）")
    return parser.parse_args()


def resolve_date(date_str):
    """対象日を date 型で返す。未指定なら JST 当日。"""
    if date_str:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    return datetime.now(JST).date()


def output_filename(source, target):
    """--source と対象日から中間JSONのファイル名を決める。"""
    return f"{target.isoformat()}.{source}.json"


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


def main():
    args = parse_arguments()
    if not args.token:
        raise SystemExit("Slackトークンが未指定です（--token または環境変数 SLACK_TOKEN）")

    target = resolve_date(args.date)

    data = {
        "date": target.isoformat(),
        "slack": collect_slack(args.token, target),
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / output_filename(args.source, target)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"収集完了: {out_path}")
    print(f"  Slack: {len(data['slack']['channels'])} チャンネル/DM")


if __name__ == "__main__":
    main()
