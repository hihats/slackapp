#!/usr/bin/env python3
"""
Slack Monthly Message Count Script

特定のチャンネルから特定の文言を含むメッセージを月ごとに集計します。
Search APIを使用した高速検索、スレッド返信を含む包括的集計を実行します。
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from typing import Dict, List

from slack_sdk import WebClient

from slack_search import SlackSearchError, build_query, search_all_messages


def parse_arguments():
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(
        description="特定チャンネルから特定文言を含むメッセージを月ごとに集計"
    )
    parser.add_argument("--token", required=True, help="Slack API トークン")
    parser.add_argument("--channel", required=True, help="チャンネルID")
    parser.add_argument("--keyword", required=True, help="検索キーワード（完全一致）")
    parser.add_argument("--months", type=int, default=3, help="検索する過去月数 (デフォルト: 3)")
    parser.add_argument("--output", required=True, help="出力JSONファイルパス")
    return parser.parse_args()


def fetch_messages(client: WebClient, channel_id: str, keyword: str, months: int) -> List[Dict]:
    """
    Search APIでメッセージを検索し、キーワードフィルタして返す。
    """
    today = datetime.now()
    after_date = (today - relativedelta(months=months)).replace(day=1).strftime("%Y-%m-%d")
    query = build_query(keyword=keyword, channel_id=channel_id, after_date=after_date)

    try:
        all_matches = search_all_messages(client, query, sort="timestamp", sort_dir="asc")
    except SlackSearchError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # キーワードフィルタ（スクリプト固有ロジック）
    messages = [
        match for match in all_matches
        if keyword.lower() in match.get("text", "").lower()
    ]

    print(f"\nSearch completed: {len(messages)} filtered messages (from {len(all_matches)} total)")
    return messages


def get_month_key(timestamp: float) -> tuple:
    """
    タイムスタンプから月キーを生成
    Returns: (month_key, start_date, end_date)
    """
    dt = datetime.fromtimestamp(timestamp)

    # 月初日
    month_start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 月末日を計算
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)
    month_end = next_month - timedelta(seconds=1)

    # YYYY-MM形式のキーを生成
    month_key = dt.strftime("%Y-%m")

    return month_key, month_start.date(), month_end.date()


def aggregate_by_month(messages: List[Dict]) -> Dict[str, Dict]:
    """メッセージを月ごとに集計"""
    monthly_counts = defaultdict(lambda: {"count": 0, "start_date": None, "end_date": None})

    for message in messages:
        timestamp = float(message.get("ts", 0))
        month_key, start_date, end_date = get_month_key(timestamp)

        monthly_counts[month_key]["count"] += 1
        monthly_counts[month_key]["start_date"] = start_date.isoformat()
        monthly_counts[month_key]["end_date"] = end_date.isoformat()

    return dict(monthly_counts)


def format_output(channel_id: str, keyword: str, months: int,
                  monthly_counts: Dict, total_messages: int) -> Dict:
    """出力用JSONデータを整形"""
    return {
        "summary": {
            "channel_id": channel_id,
            "keyword": keyword,
            "search_period_months": months,
            "total_messages": total_messages,
            "generated_at": datetime.now().isoformat()
        },
        "monthly_counts": dict(sorted(monthly_counts.items()))
    }


def save_results(data: Dict, output_path: str):
    """結果をJSONファイルに保存"""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {output_path}")


def print_summary(data: Dict):
    """集計結果のサマリーを表示"""
    print(f"\n=== 月次メッセージ集計結果 ===")
    print(f"チャンネル: {data['summary']['channel_id']}")
    print(f"検索キーワード: {data['summary']['keyword']}")
    print(f"検索期間: 過去{data['summary']['search_period_months']}ヶ月間")
    print(f"合計メッセージ数: {data['summary']['total_messages']}")
    print(f"\n月別集計:")
    print(f"{'月':<12} {'期間':<25} {'メッセージ数':>12}")
    print("-" * 50)

    for month_key, month_data in data["monthly_counts"].items():
        date_range = f"{month_data['start_date']} ~ {month_data['end_date']}"
        print(f"{month_key:<12} {date_range:<25} {month_data['count']:>12}")


def main():
    args = parse_arguments()

    # Slack クライアントを初期化
    client = WebClient(token=args.token)

    # Search APIでメッセージを検索
    print(f"Searching for messages containing '{args.keyword}' in channel {args.channel}...")
    print(f"Search period: last {args.months} months")
    print("Using Search API for fast cross-message search (including threads)...")

    messages = fetch_messages(client, args.channel, args.keyword, args.months)

    if not messages:
        print(f"\nNo messages found containing '{args.keyword}' in the specified period.")
        # 空の結果を保存
        empty_result = format_output(args.channel, args.keyword, args.months, {}, 0)
        save_results(empty_result, args.output)
        sys.exit(0)

    print(f"\nFound {len(messages)} messages containing the keyword.")

    # 月ごとに集計
    monthly_counts = aggregate_by_month(messages)

    # 出力データを整形
    output_data = format_output(
        args.channel,
        args.keyword,
        args.months,
        monthly_counts,
        len(messages)
    )

    # サマリーを表示
    print_summary(output_data)

    # 結果を保存
    save_results(output_data, args.output)


if __name__ == "__main__":
    main()
