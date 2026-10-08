"""
指定ユーザーの発言だけを search.messages で取り出し、JSON に保存する。
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from slack_sdk import WebClient

from slack_search import SlackSearchError, build_query, search_all_messages
from slack_user import resolve_user_id

JST = timezone(timedelta(hours=9))
DEFAULT_DAYS = 30


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description="指定ユーザーの発言だけを取り出す")
    parser.add_argument("--user", required=True, help="対象ユーザーIDまたは表示名")
    parser.add_argument("--token", type=str, default=os.environ.get("SLACK_TOKEN"),
                        help="Slackユーザートークン（search:read 必須／既定は環境変数 SLACK_TOKEN）")
    parser.add_argument("--channel", help="チャンネルID（省略時は全チャンネル横断）")
    parser.add_argument("--keyword", help="本文キーワード（フレーズ一致）")
    parser.add_argument("--days", type=int,
                        help=f"遡る日数（既定: {DEFAULT_DAYS}／--after・--before と併用不可）")
    parser.add_argument("--after", type=date.fromisoformat, help="この日以降（当日を含む, YYYY-MM-DD）")
    parser.add_argument("--before", type=date.fromisoformat, help="この日以前（当日を含む, YYYY-MM-DD）")
    parser.add_argument("--output", default="user_posts.json", help="出力JSONファイル（既定: user_posts.json）")
    args = parser.parse_args(argv)
    # add_mutually_exclusive_group は「--days 対 (--after または --before)」を表せないため手で検査する
    if args.days is not None and (args.after or args.before):
        parser.error("--days と --after/--before は同時に指定できません")
    return args


def _shift(d, delta_days):
    return (d + timedelta(days=delta_days)).isoformat() if d else None


def resolve_date_range(days, after, before, today=None):
    """期間指定を search.messages の after:/before: 用の日付文字列に変換する。"""
    if after or before:
        # Slack の after:/before: は指定日を含まない（公式ドキュメントに記載がなく、実測で確認）。
        # 1日外側にずらして指定日を含める
        return _shift(after, -1), _shift(before, 1)
    today = today or datetime.now(JST).date()
    span = DEFAULT_DAYS if days is None else days
    return (today - timedelta(days=span)).isoformat(), None


def build_user_query(user_id, channel_id, keyword, after_date, before_date):
    """from:<@user> に各絞り込み条件を組み合わせたクエリを作る。"""
    extra = f"from:<@{user_id}>"
    if before_date:
        # build_query に before 引数がない。共通モジュールを変えず extra で渡す
        extra += f" before:{before_date}"
    return build_query(keyword=keyword, channel_id=channel_id, after_date=after_date, extra=extra)


def fetch_user_posts(client, query):
    """search.messages の全ページを取得し、(channel, ts) で重複を除く。"""
    seen = set()
    posts = []
    for match in search_all_messages(client, query):
        key = ((match.get("channel") or {}).get("id"), match.get("ts"))
        if key in seen:
            continue
        seen.add(key)
        posts.append(match)
    return posts


def permalink_thread_ts(match):
    """permalink の thread_ts クエリを返す（なければ None）。"""
    # search.messages の match には thread_ts フィールドがないため permalink から取る
    params = parse_qs(urlparse(match.get("permalink", "")).query)
    return params.get("thread_ts", [None])[0]


def is_thread_reply(match):
    """permalink の thread_ts が自身の ts と異なればスレッド返信と判定する。"""
    thread_ts = permalink_thread_ts(match)
    return thread_ts is not None and thread_ts != match.get("ts")


def format_post(match):
    """search.messages の match を出力用の dict にする。"""
    channel = match.get("channel") or {}
    posted_at = datetime.fromtimestamp(float(match["ts"]), JST)
    return {
        "ts": match["ts"],
        "datetime": posted_at.strftime("%Y-%m-%d %H:%M:%S"),
        "channel_id": channel.get("id"),
        "channel_name": channel.get("name"),
        "text": match.get("text", ""),
        "permalink": match.get("permalink"),
        "is_thread_reply": is_thread_reply(match),
    }


def save_results(data, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    args = parse_arguments()
    if not args.token:
        raise SystemExit("Slackトークンが未指定です（--token または環境変数 SLACK_TOKEN）")

    client = WebClient(token=args.token)
    user_id = resolve_user_id(client, args.user)
    after_date, before_date = resolve_date_range(args.days, args.after, args.before)
    query = build_user_query(user_id, args.channel, args.keyword, after_date, before_date)
    print(f"Search query: {query}")

    try:
        matches = fetch_user_posts(client, query)
    except SlackSearchError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    posts = [format_post(m) for m in matches]
    save_results({"user_id": user_id, "query": query, "count": len(posts), "messages": posts}, args.output)
    print(f"保存完了: {args.output}（{len(posts)} 件）")


if __name__ == "__main__":
    main()
