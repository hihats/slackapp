"""
指定ユーザーの発言から、質問と回答のセットを集める。

collect: 本人の発言を search.messages で取り、スレッドの親を質問・返信を回答として
         conversations.replies でスレッド全体を取る。スレッド外の投稿は standalone_posts に残す。
context: 「回答」と判定されたスレッド外の投稿（判定は呼び出し側のスキル）について、
         直前 N 件のメッセージを取る。
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

from slack_sdk import WebClient

from slack_conversations import fetch_all_thread_replies, fetch_channel_history
from slack_search import SlackSearchError
from slack_user import resolve_user_id
# 日付境界の補正を含む発言取得は user_posts と揃える。共通モジュール化は PR #22 の差分を変えないため見送った
from user_posts import (
    JST, build_user_query, fetch_user_posts, format_post, permalink_thread_ts, resolve_date_range,
)

ANSWERER = "answerer"
ASKER = "asker"
STANDALONE = "standalone"
DEFAULT_LIMIT = 20
OUTPUT_DIR = Path("outputs/qa_pairs")
# conversations.replies / history は Tier 3。共通関数は呼び出しの間で待たないためこちらで待つ
TIER3_INTERVAL = 1.5


def _has_date_conflict(args):
    return args.days is not None and bool(args.after or args.before)


def parse_arguments(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--token", type=str, default=os.environ.get("SLACK_TOKEN"),
                        help="Slackユーザートークン（既定は環境変数 SLACK_TOKEN）")
    common.add_argument("--output", help="出力JSONファイル")

    parser = argparse.ArgumentParser(description="指定ユーザーの発言から質問と回答のセットを集める")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", parents=[common], help="スレッドの Q&A とスレッド外の投稿を集める")
    collect.add_argument("--user", required=True, help="対象ユーザーIDまたは表示名")
    collect.add_argument("--channel", help="チャンネルID（省略時は全チャンネル横断）")
    collect.add_argument("--keyword", help="本文キーワード（フレーズ一致）")
    collect.add_argument("--days", type=int, help="遡る日数（既定: 30／--after・--before と併用不可）")
    collect.add_argument("--after", type=date.fromisoformat, help="この日以降（当日を含む, YYYY-MM-DD）")
    collect.add_argument("--before", type=date.fromisoformat, help="この日以前（当日を含む, YYYY-MM-DD）")

    context = sub.add_parser("context", parents=[common], help="指定した投稿の直前 N 件を取る")
    context.add_argument("--targets", required=True, help='[{"channel_id", "ts"}] の JSON ファイル')
    context.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"遡る件数（既定: {DEFAULT_LIMIT}）")

    args = parser.parse_args(argv)
    # add_mutually_exclusive_group は「--days 対 (--after または --before)」を表せないため手で検査する
    if args.command == "collect" and _has_date_conflict(args):
        parser.error("--days と --after/--before は同時に指定できません")
    return args


def classify_post(match):
    """permalink の thread_ts から (role, thread_ts) を決める。"""
    thread_ts = permalink_thread_ts(match)
    if thread_ts is None:
        return STANDALONE, None
    return (ASKER if thread_ts == match.get("ts") else ANSWERER), thread_ts


def group_threads(matches):
    """本人の発言を (channel, thread_ts) 単位のスレッドと、スレッド外の投稿に分ける。"""
    threads, standalone = {}, []
    for match in matches:
        role, thread_ts = classify_post(match)
        if role == STANDALONE:
            standalone.append(match)
            continue
        channel = match.get("channel") or {}
        thread = threads.setdefault((channel.get("id"), thread_ts), {
            "role": role,
            "channel_id": channel.get("id"),
            "channel_name": channel.get("name"),
            "thread_ts": thread_ts,
            "permalink": match.get("permalink"),
        })
        if role == ASKER:
            # 本人が親なら、同じスレッドに自分の返信があっても質問者側として扱う
            thread["role"] = ASKER
    return list(threads.values()), standalone


def fetch_thread(client, channel_id, thread_ts):
    return fetch_all_thread_replies(client, channel_id, thread_ts, skip_parent=False)


def format_message(msg):
    """conversations.* のメッセージを出力用の dict にする。"""
    posted_at = datetime.fromtimestamp(float(msg["ts"]), JST)
    return {
        "ts": msg["ts"],
        "datetime": posted_at.strftime("%Y-%m-%d %H:%M:%S"),
        "user": msg.get("user") or msg.get("bot_id"),
        "text": msg.get("text", ""),
    }


def build_pair(thread, messages, user_id):
    """スレッドの先頭を質問、残りを回答として 1 組にする。"""
    question, *replies = messages
    answers = [{**format_message(m), "is_target_user": m.get("user") == user_id} for m in replies]
    return {**thread, "source": "thread", "question": format_message(question), "answers": answers}


def collect_qa_pairs(client, threads, user_id):
    """スレッドを 1 件ずつ取得して Q&A の組にする。取得できなかったものは飛ばす。"""
    pairs = []
    for i, thread in enumerate(threads):
        if i:
            time.sleep(TIER3_INTERVAL)
        messages = fetch_thread(client, thread["channel_id"], thread["thread_ts"])
        if not messages:
            print(f"Skip: スレッドを取得できませんでした {thread['channel_id']} {thread['thread_ts']}")
            continue
        pairs.append(build_pair(thread, messages, user_id))
    return pairs


def fetch_preceding(client, channel_id, ts, limit):
    """ts より前の最新 limit 件を古い順で返す。"""
    # fetch_all_channel_history だと全履歴を辿るため、最初の 1 ページだけ使う。
    # latest は ts 文字列のまま渡す（float にすると末尾の桁が丸まり境界がずれうる）
    pages = fetch_channel_history(client, channel_id, latest=ts, limit=limit)
    newest_first = next(pages, [])
    return [format_message(m) for m in reversed(newest_first)]


def save_json(data, output_path):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"保存完了: {path}")


def run_collect(client, args):
    user_id = resolve_user_id(client, args.user)
    after_date, before_date = resolve_date_range(args.days, args.after, args.before)
    query = build_user_query(user_id, args.channel, args.keyword, after_date, before_date)
    print(f"Search query: {query}")

    threads, standalone = group_threads(fetch_user_posts(client, query))
    print(f"スレッド {len(threads)} 件を取得します（約 {len(threads) * TIER3_INTERVAL:.0f} 秒）")
    pairs = collect_qa_pairs(client, threads, user_id)

    data = {
        "user_id": user_id,
        "query": query,
        "qa_pairs": pairs,
        "standalone_posts": [format_post(m) for m in standalone],
    }
    save_json(data, args.output or OUTPUT_DIR / f"{user_id}.json")
    print(f"  Q&A: {len(pairs)} 組 / スレッド外の投稿: {len(standalone)} 件")


def run_context(client, args):
    targets = json.loads(Path(args.targets).read_text(encoding="utf-8"))
    results = []
    for i, target in enumerate(targets):
        if i:
            time.sleep(TIER3_INTERVAL)
        preceding = fetch_preceding(client, target["channel_id"], target["ts"], args.limit)
        results.append({**target, "preceding": preceding})
    save_json({"targets": results}, args.output or OUTPUT_DIR / "context.json")


def main():
    args = parse_arguments()
    if not args.token:
        raise SystemExit("Slackトークンが未指定です（--token または環境変数 SLACK_TOKEN）")

    client = WebClient(token=args.token)
    runner = run_collect if args.command == "collect" else run_context
    try:
        runner(client, args)
    except SlackSearchError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
