#!/usr/bin/env python3
"""
Slack Weekly Message Count Script

特定のチャンネルから特定の文言を含むメッセージを週ごとに集計します。
Search APIを使用した高速検索、スレッド返信を含む包括的集計を実行します。
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def parse_arguments():
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(
        description="特定チャンネルから特定文言を含むメッセージを週ごとに集計"
    )
    parser.add_argument("--token", required=True, help="Slack API トークン")
    parser.add_argument("--channel", required=True, help="チャンネルID")
    parser.add_argument("--keyword", required=True, help="検索キーワード（完全一致）")
    parser.add_argument("--days", type=int, default=30, help="検索する過去日数 (デフォルト: 30)")
    parser.add_argument("--output", required=True, help="出力JSONファイルパス")
    return parser.parse_args()


def search_messages_with_api(client: WebClient, channel_id: str, keyword: str, days: int) -> List[Dict]:
    """
    Search APIを使用してメッセージを検索する
    スレッド返信、Bot/Appメッセージも含めて検索
    100件以上のメッセージもページベースのページネーションで全て取得
    """
    messages = []

    # 検索期間を計算
    after_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Search APIクエリを構築（大文字小文字を区別しない完全一致）
    query = f'in:{channel_id} "{keyword}" after:{after_date}'

    try:
        page = 1
        has_more = True
        total_processed = 0

        while has_more:
            print(f"Searching messages (page {page})...")

            # ページベースのページネーションを使用（より確実）
            response = client.search_messages(
                query=query,
                sort="timestamp", 
                sort_dir="asc",
                count=100,  # 1ページあたりの最大値
                page=page
            )

            if not response["ok"]:
                print(f"Search API error: {response}", file=sys.stderr)
                break

            matches = response.get("messages", {}).get("matches", [])
            pagination = response.get("messages", {}).get("pagination", {})
            
            # 現在のページ情報を表示
            total_results = pagination.get("total_count", 0)
            page_count = pagination.get("page_count", 1)
            current_page = pagination.get("page", page)
            
            print(f"  Page {current_page}/{page_count}: {len(matches)} matches found")
            print(f"  Total results available: {total_results}")

            # メッセージを抽出
            page_added = 0
            for match in matches:
                # キーワードの完全一致を確認（大文字小文字を区別しない）
                text = match.get("text", "")
                if keyword.lower() in text.lower():
                    messages.append(match)
                    page_added += 1
                    
            total_processed += len(matches)
            print(f"  Added {page_added} messages from this page")
            print(f"  Total messages collected so far: {len(messages)}")

            # 次のページがあるか確認（page-based pagination）
            if current_page < page_count:
                page += 1
                # APIレート制限対策として少し待機（Tier 3: 50リクエスト/分）
                time.sleep(1.5)
            else:
                has_more = False
                
            # 安全対策：異常に多いページ数の場合は停止
            if page > 50:  # 5000件（100*50）以上は停止
                print(f"Warning: Stopped after {page-1} pages to prevent excessive API calls")
                break

        print(f"\nSearch completed:")
        print(f"  Total API responses processed: {total_processed} messages")
        print(f"  Final filtered messages: {len(messages)}")

    except SlackApiError as e:
        if e.response["error"] == "missing_scope":
            print("Error: Token needs 'search:read' scope for Search API", file=sys.stderr)
            print("Please ensure your token has the search:read scope enabled.", file=sys.stderr)
        else:
            print(f"Slack API error: {e}", file=sys.stderr)
        sys.exit(1)

    return messages


def get_sunday_week_key(timestamp: float) -> tuple:
    """
    タイムスタンプから日曜始まりの週キーを生成
    Returns: (week_key, start_date, end_date)
    """
    dt = datetime.fromtimestamp(timestamp)

    # 日曜日を週の始まりとして計算
    days_since_sunday = (dt.weekday() + 1) % 7
    week_start = dt - timedelta(days=days_since_sunday)
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)

    # ISO週番号形式のキーを生成（ただし日曜始まり）
    # 週の木曜日を基準にISO週番号を決定
    thursday = week_start + timedelta(days=4)
    iso_year, iso_week, _ = thursday.isocalendar()
    week_key = f"{iso_year}-W{iso_week:02d}"

    return week_key, week_start.date(), week_end.date()


def aggregate_by_week(messages: List[Dict]) -> Dict[str, Dict]:
    """メッセージを週ごとに集計（日曜始まり）"""
    weekly_counts = defaultdict(lambda: {"count": 0, "start_date": None, "end_date": None})

    for message in messages:
        timestamp = float(message.get("ts", 0))
        week_key, start_date, end_date = get_sunday_week_key(timestamp)

        weekly_counts[week_key]["count"] += 1
        weekly_counts[week_key]["start_date"] = start_date.isoformat()
        weekly_counts[week_key]["end_date"] = end_date.isoformat()

    return dict(weekly_counts)


def format_output(channel_id: str, keyword: str, days: int,
                  weekly_counts: Dict, total_messages: int) -> Dict:
    """出力用JSONデータを整形"""
    return {
        "summary": {
            "channel_id": channel_id,
            "keyword": keyword,
            "search_period_days": days,
            "total_messages": total_messages,
            "generated_at": datetime.now().isoformat()
        },
        "weekly_counts": dict(sorted(weekly_counts.items()))
    }


def save_results(data: Dict, output_path: str):
    """結果をJSONファイルに保存"""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {output_path}")


def print_summary(data: Dict):
    """集計結果のサマリーを表示"""
    print(f"\n=== 週次メッセージ集計結果 ===")
    print(f"チャンネル: {data['summary']['channel_id']}")
    print(f"検索キーワード: {data['summary']['keyword']}")
    print(f"検索期間: 過去{data['summary']['search_period_days']}日間")
    print(f"合計メッセージ数: {data['summary']['total_messages']}")
    print(f"\n週別集計（日曜始まり）:")
    print(f"{'週':<12} {'期間':<25} {'メッセージ数':>12}")
    print("-" * 50)

    for week_key, week_data in data["weekly_counts"].items():
        date_range = f"{week_data['start_date']} ~ {week_data['end_date']}"
        print(f"{week_key:<12} {date_range:<25} {week_data['count']:>12}")


def main():
    args = parse_arguments()

    # Slack クライアントを初期化
    client = WebClient(token=args.token)

    # Search APIでメッセージを検索
    print(f"Searching for messages containing '{args.keyword}' in channel {args.channel}...")
    print(f"Search period: last {args.days} days")
    print("Using Search API for fast cross-message search (including threads)...")

    messages = search_messages_with_api(client, args.channel, args.keyword, args.days)

    if not messages:
        print(f"\nNo messages found containing '{args.keyword}' in the specified period.")
        # 空の結果を保存
        empty_result = format_output(args.channel, args.keyword, args.days, {}, 0)
        save_results(empty_result, args.output)
        sys.exit(0)

    print(f"\nFound {len(messages)} messages containing the keyword.")

    # 週ごとに集計
    weekly_counts = aggregate_by_week(messages)

    # 出力データを整形
    output_data = format_output(
        args.channel,
        args.keyword,
        args.days,
        weekly_counts,
        len(messages)
    )

    # サマリーを表示
    print_summary(output_data)

    # 結果を保存
    save_results(output_data, args.output)


if __name__ == "__main__":
    main()