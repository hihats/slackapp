"""
指定ユーザーの発言から、質問と回答のセットを集める。

collect: 本人の発言を search.messages で取り、スレッドの親を質問・返信を回答として
         conversations.replies でスレッド全体を取る。スレッド外の投稿は standalone_posts に残す。
context: 「回答」と判定されたスレッド外の投稿（判定は呼び出し側のスキル）について、
         直前 N 件のメッセージを取る。
index:   collect の出力から、判定用の索引を作る（Slack は呼ばない）。
render:  collect の出力と判定ファイルから Markdown を作る（Slack は呼ばない）。
merge:   Markdown をユーザー×チャンネルの蓄積ファイルに積み上げる（Slack は呼ばない）。
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from slack_conversations import fetch_all_thread_replies, fetch_channel_history
from slack_search import SlackSearchError
from slack_user import resolve_user_id
# 日付境界の補正を含む発言取得は user_posts と揃える。共通モジュール化は PR #22 の差分を変えないため見送った
from user_posts import (
    JST, build_user_query, fetch_user_posts, format_post, permalink_thread_ts, resolve_date_range,
)
from qa_pairs_knowledge import merge_knowledge
from qa_pairs_markdown import build_index, render_markdown

ANSWERER = "answerer"
ASKER = "asker"
DEFAULT_LIMIT = 20
OUTPUT_DIR = Path("outputs/qa_pairs")
# 実行ごとのディレクトリ内のファイル名。スキルや README はここに依存せず collect の表示を使う
RUN_FILES = {"collect": "collect.json", "index": "index.txt", "targets": "targets.json",
             "context": "context.json", "judgement": "judgement.json", "markdown": "qa_pairs.md"}
# conversations.replies / history は Tier 3。共通関数は呼び出しの間で待たないためこちらで待つ
TIER3_INTERVAL = 1.5
# 飛ばすのはそのスレッドだけの問題に限る。認証・スコープ等は全スレッドで失敗するため飛ばさず止める
SKIPPABLE_THREAD_ERRORS = {"thread_not_found", "channel_not_found"}


def _has_date_conflict(args):
    return args.days is not None and bool(args.after or args.before)


def parse_arguments(argv=None):
    slack = argparse.ArgumentParser(add_help=False)
    slack.add_argument("--token", type=str, default=os.environ.get("SLACK_TOKEN"),
                       help="Slackユーザートークン（既定は環境変数 SLACK_TOKEN）")
    run = argparse.ArgumentParser(add_help=False)
    run.add_argument("--run-dir", required=True, help="collect が表示した RUN_DIR")

    parser = argparse.ArgumentParser(description="指定ユーザーの発言から質問と回答のセットを集める")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", parents=[slack], help="スレッドの Q&A とスレッド外の投稿を集める")
    collect.add_argument("--user", required=True, help="対象ユーザーIDまたは表示名")
    collect.add_argument("--channel", help="チャンネルID（省略時は全チャンネル横断）")
    collect.add_argument("--keyword", help="本文キーワード（フレーズ一致）")
    collect.add_argument("--days", type=int, help="遡る日数（既定: 30／--after・--before と併用不可）")
    collect.add_argument("--after", type=date.fromisoformat, help="この日以降（当日を含む, YYYY-MM-DD）")
    collect.add_argument("--before", type=date.fromisoformat, help="この日以前（当日を含む, YYYY-MM-DD）")
    collect.add_argument("--output-dir", type=Path, default=OUTPUT_DIR,
                         help=f"実行ごとのディレクトリを作る場所（既定: {OUTPUT_DIR}）")

    context = sub.add_parser("context", parents=[slack, run], help="指定した投稿の直前 N 件を取る")
    context.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"遡る件数（既定: {DEFAULT_LIMIT}）")

    sub.add_parser("index", parents=[run], help="判定用の索引を作る")

    render = sub.add_parser("render", parents=[run], help="Markdown を作る")
    render.add_argument("--period", required=True, help="タイトルに出す期間")

    merge = sub.add_parser("merge", parents=[run], help="Markdown を蓄積ファイルに積み上げる")
    merge.add_argument("--knowledge", type=Path, required=True,
                       help="蓄積ファイル（なければ作る）")
    merge.add_argument("--period", required=True, help="今回取り込む期間（蓄積ファイルに記録する）")

    args = parser.parse_args(argv)
    # add_mutually_exclusive_group は「--days 対 (--after または --before)」を表せないため手で検査する
    if args.command == "collect" and _has_date_conflict(args):
        parser.error("--days と --after/--before は同時に指定できません")
    return args


def group_threads(matches):
    """本人の発言を (channel, thread_ts) 単位のスレッドと、スレッド外の投稿に分ける。"""
    threads, standalone = {}, []
    for match in matches:
        thread_ts = permalink_thread_ts(match)
        if thread_ts is None:
            standalone.append(match)
            continue
        channel = match.get("channel") or {}
        threads.setdefault((channel.get("id"), thread_ts), {
            "channel_id": channel.get("id"),
            "channel_name": channel.get("name"),
            "thread_ts": thread_ts,
            "permalink": match.get("permalink"),
        })
    return list(threads.values()), _drop_thread_parents(standalone, threads)


def _drop_thread_parents(standalone, threads):
    """スレッドとして集めた親投稿を、スレッド外の投稿から除く。"""
    # 親のリンクに thread_ts が付かないと、同じ投稿がスレッドとスレッド外の両方に入る
    return [m for m in standalone
            if ((m.get("channel") or {}).get("id"), m.get("ts")) not in threads]


def fetch_thread(client, channel_id, thread_ts):
    """スレッド全体を取る。スレッド固有のエラーなら空で返し、それ以外はそのまま投げる。"""
    try:
        return fetch_all_thread_replies(client, channel_id, thread_ts, skip_parent=False)
    except SlackApiError as e:
        error = e.response.get("error")
        if error not in SKIPPABLE_THREAD_ERRORS:
            raise
        print(f"Slack API エラー: {error}")
        return []


def format_message(msg):
    """conversations.* のメッセージを出力用の dict にする。"""
    posted_at = datetime.fromtimestamp(float(msg["ts"]), JST)
    return {
        "ts": msg["ts"],
        "datetime": posted_at.strftime("%Y-%m-%d %H:%M:%S"),
        # アプリの投稿は user（U…）も持つため、bot と見分けられるよう bot_id を先に見る
        "user": msg.get("bot_id") or msg.get("user"),
        "text": msg.get("text", ""),
    }


def build_pair(thread, messages, user_id):
    """スレッドの先頭を質問、残りを回答として 1 組にする。"""
    question, *replies = messages
    # 検索結果に親が含まれるとは限らない（期間外・キーワード不一致）ため、取得した親の発言者で決める
    role = ASKER if question.get("user") == user_id else ANSWERER
    answers = [{**format_message(m), "is_target_user": m.get("user") == user_id} for m in replies]
    return {"role": role, **thread, "source": "thread",
            "question": format_message(question), "answers": answers}


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
    # fetch_all_channel_history だと全履歴を辿るため、limit 件に達したページで止める。
    # 1 ページ目だけにしないのは、履歴が残っていても limit 未満で返ることがあるため（Slack 公式の limit の説明）。
    # latest は ts 文字列のまま渡す（float にすると末尾の桁が丸まり境界がずれうる）
    newest_first = []
    for page in fetch_channel_history(client, channel_id, latest=ts, limit=limit):
        newest_first.extend(page)
        if len(newest_first) >= limit:
            break
    return [format_message(m) for m in reversed(newest_first[:limit])]


def new_run_dir(base, user_id, now):
    """<base>/<user_id>/<JST の日時> を作って返す。"""
    run_dir = Path(base) / user_id / now.astimezone(JST).strftime("%Y%m%d-%H%M%S")
    # 同じ秒に実行されても前の結果を上書きしないよう、既にあれば止める
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def run_file(run_dir, role):
    return Path(run_dir) / RUN_FILES[role]


def print_run_files(run_dir):
    print(f"RUN_DIR: {run_dir}")
    for role in RUN_FILES:
        print(f"  {role}: {run_file(run_dir, role)}")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(data, output_path):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"保存完了: {path}")


def save_text(text, output_path):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
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
    # 取得に失敗したとき空のディレクトリを残さないよう、保存の直前に作る
    run_dir = new_run_dir(args.output_dir, user_id, datetime.now(JST))
    save_json(data, run_file(run_dir, "collect"))
    print(f"  Q&A: {len(pairs)} 組 / スレッド外の投稿: {len(standalone)} 件")
    print_run_files(run_dir)


def run_context(client, args):
    targets = load_json(run_file(args.run_dir, "targets"))
    results = []
    for i, target in enumerate(targets):
        if i:
            time.sleep(TIER3_INTERVAL)
        preceding = fetch_preceding(client, target["channel_id"], target["ts"], args.limit)
        results.append({**target, "preceding": preceding})
    save_json({"targets": results}, run_file(args.run_dir, "context"))


def run_index(args):
    data = load_json(run_file(args.run_dir, "collect"))
    save_text(build_index(data), run_file(args.run_dir, "index"))


def run_render(args):
    data = load_json(run_file(args.run_dir, "collect"))
    judgement = load_json(run_file(args.run_dir, "judgement"))
    save_text(render_markdown(data, judgement, args.period), run_file(args.run_dir, "markdown"))


def run_merge(args):
    knowledge = args.knowledge.read_text(encoding="utf-8") if args.knowledge.exists() else ""
    run_md = run_file(args.run_dir, "markdown").read_text(encoding="utf-8")
    merged, changes = merge_knowledge(knowledge, run_md, args.period)
    save_text(merged, args.knowledge)
    print(f"追加・変更した組: {len(changes)} 組")
    for heading in changes:
        print(f"  {heading}")


SLACK_RUNNERS = {"collect": run_collect, "context": run_context}
OFFLINE_RUNNERS = {"index": run_index, "render": run_render, "merge": run_merge}


def main():
    args = parse_arguments()
    if args.command in OFFLINE_RUNNERS:
        OFFLINE_RUNNERS[args.command](args)
        return
    if not args.token:
        raise SystemExit("Slackトークンが未指定です（--token または環境変数 SLACK_TOKEN）")

    client = WebClient(token=args.token)
    try:
        SLACK_RUNNERS[args.command](client, args)
    except SlackSearchError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
