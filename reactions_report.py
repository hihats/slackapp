#!/usr/bin/env python3
"""
Slack Reactions Report Script

指定ユーザーが投稿したメッセージのうち、リアクションが付いたものを
指定期間で収集する。

Search API でメッセージを検索し、reactions.get API でリアクション詳細を取得する。
ポジティブかどうかの判断は後続の処理に委ねる。
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from slack_user import resolve_user_id
from slack_search import SlackSearchError, build_query, handle_rate_limit, search_all_messages


def parse_arguments():
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(
        description="指定ユーザーの投稿に対するリアクションを収集",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--token", required=True, help="Slack API トークン（search:read スコープ必須）")
    parser.add_argument("--user", required=True, help="対象ユーザーIDまたは表示名（例: U12345ABC, hisahiro.tsukamoto）")
    parser.add_argument("--days", type=int, default=30, help="検索する過去日数 (デフォルト: 30)")
    parser.add_argument("--channel", default=None, help="チャンネルID（省略時は全チャンネル）")
    parser.add_argument("--output", required=True, help="出力JSONファイルパス")
    return parser.parse_args()


def fetch_user_messages(
    client: WebClient, user_id: str, days: int, channel_id: Optional[str] = None
) -> List[Dict]:
    """Search API で指定ユーザーの投稿を取得し、重複排除して返す。"""
    after_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    query = build_query(
        channel_id=channel_id,
        after_date=after_date,
        extra=f"from:<@{user_id}>",
    )
    print(f"Search query: {query}")

    try:
        all_matches = search_all_messages(client, query, sort="timestamp", sort_dir="asc")
    except SlackSearchError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # (channel_id, ts) で重複排除
    seen = set()
    messages = []
    for match in all_matches:
        key = (match.get("channel", {}).get("id"), match.get("ts"))
        if key not in seen:
            seen.add(key)
            messages.append(match)

    print(f"Search completed: {len(messages)} unique messages (from {len(all_matches)} total)")
    return messages


def enrich_with_reactions(client: WebClient, messages: List[Dict]) -> List[Dict]:
    """各メッセージに reactions.get でリアクション情報を付与する。"""
    total = len(messages)
    for i, msg in enumerate(messages):
        channel_id = msg.get("channel", {}).get("id")
        ts = msg.get("ts")

        if not channel_id or not ts:
            msg["_reactions"] = []
            continue

        try:
            response = handle_rate_limit(
                client.reactions_get,
                channel=channel_id,
                timestamp=ts,
                full=True,
            )
            if response and response["ok"]:
                message_data = response.get("message", {})
                msg["_reactions"] = message_data.get("reactions", [])
            else:
                msg["_reactions"] = []
        except SlackApiError:
            # リアクション無しのメッセージや権限エラー時は空リストで継続
            msg["_reactions"] = []

        if (i + 1) % 10 == 0 or (i + 1) == total:
            print(f"  Reactions fetched: {i + 1}/{total}")

        time.sleep(1.5)  # Tier 3: 50 requests/min

    return messages


def format_messages(messages: List[Dict]) -> List[Dict]:
    """メッセージデータを整形し、リアクション付きのもののみ返す。"""
    formatted = []
    for msg in messages:
        raw_reactions = msg.get("_reactions", [])
        if not raw_reactions:
            continue

        channel_info = msg.get("channel", {})
        ts = msg.get("ts", "")

        try:
            dt = datetime.fromtimestamp(float(ts))
            datetime_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            datetime_str = ""

        reactions = []
        total_count = 0
        for r in raw_reactions:
            count = r.get("count", 0)
            total_count += count
            reactions.append({
                "name": r.get("name", ""),
                "count": count,
                "users": [u for u in r.get("users", [])],
            })

        formatted.append({
            "channel_id": channel_info.get("id", ""),
            "channel_name": channel_info.get("name", ""),
            "timestamp": ts,
            "datetime": datetime_str,
            "text": msg.get("text", ""),
            "permalink": msg.get("permalink", ""),
            "reactions": reactions,
            "total_reaction_count": total_count,
        })

    return formatted


def aggregate_results(
    formatted_messages: List[Dict],
    total_posts: int,
    user_id: str,
    days: int,
    channel_id: Optional[str],
) -> Dict:
    """サマリー統計、リアクションランキング、メッセージ詳細を構造化する。"""
    posts_with_reactions = len(formatted_messages)
    total_reactions = sum(m["total_reaction_count"] for m in formatted_messages)

    # リアクションランキング
    reaction_counter = Counter()
    for m in formatted_messages:
        for r in m["reactions"]:
            reaction_counter[r["name"]] += r["count"]

    ranking = [
        {"name": name, "count": count}
        for name, count in reaction_counter.most_common()
    ]

    return {
        "summary": {
            "user_id": user_id,
            "search_period_days": days,
            "channel_id": channel_id,
            "total_posts": total_posts,
            "posts_with_reactions": posts_with_reactions,
            "total_reactions_received": total_reactions,
            "generated_at": datetime.now().isoformat(),
        },
        "reaction_ranking": ranking,
        "messages": formatted_messages,
    }


def print_summary(results: Dict):
    """集計結果のサマリーを表示"""
    s = results["summary"]
    print(f"\n=== リアクション集計結果 ===")
    print(f"対象ユーザー: {s['user_id']}")
    print(f"検索期間: 過去{s['search_period_days']}日間")
    if s["channel_id"]:
        print(f"チャンネル: {s['channel_id']}")
    print(f"投稿数: {s['total_posts']}")
    print(f"リアクション付き投稿: {s['posts_with_reactions']}")
    print(f"総リアクション数: {s['total_reactions_received']}")

    ranking = results.get("reaction_ranking", [])
    if ranking:
        print(f"\n--- リアクションランキング (Top 10) ---")
        print(f"{'Rank':<6} {'Emoji':<25} {'Count':>6}")
        print("-" * 40)
        for i, r in enumerate(ranking[:10], 1):
            print(f"{i:<6} :{r['name']}:{'':<{max(0, 22 - len(r['name']))}} {r['count']:>6}")


def save_results(results: Dict, output_path: str):
    """結果をJSONファイルに保存"""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {output_path}")


def main():
    start_time = time.time()
    args = parse_arguments()

    # Slack クライアント初期化
    client = WebClient(token=args.token)

    # ユーザーIDを解決（表示名でも指定可能）
    user_id = resolve_user_id(client, args.user)

    # Phase 1: Search API でユーザーの投稿を検索
    print(f"Searching messages from user {user_id} (last {args.days} days)...")
    messages = fetch_user_messages(client, user_id, args.days, args.channel)

    if not messages:
        print("\nNo messages found for the specified user and period.")
        empty_result = aggregate_results([], 0, user_id, args.days, args.channel)
        save_results(empty_result, args.output)
        sys.exit(0)

    # Phase 2: reactions.get でリアクション詳細を取得
    print(f"\nFetching reactions for {len(messages)} messages...")
    messages = enrich_with_reactions(client, messages)

    # リアクション付きメッセージのみ整形
    formatted = format_messages(messages)

    # 集計
    results = aggregate_results(formatted, len(messages), user_id, args.days, args.channel)

    # 出力
    print_summary(results)
    save_results(results, args.output)

    elapsed = time.time() - start_time
    print(f"\nExecution time: {elapsed:.1f} seconds")


if __name__ == "__main__":
    main()
