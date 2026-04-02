#!/usr/bin/env python3
"""
Slack Weekly Message Count Script

特定のチャンネルから特定の文言を含むメッセージを週ごとに集計します。
conversations.history でメッセージを取得し、スレッド返信も含めてキーワード検索します。
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
    parser.add_argument("--channel", required=True, help="チャンネルID (例: C07NX1JJ215)")
    parser.add_argument("--keyword", required=True, help="検索キーワード（完全一致）")
    parser.add_argument("--days", type=int, default=30, help="検索する過去日数 (デフォルト: 30)")
    parser.add_argument("--output", required=True, help="出力JSONファイルパス")
    return parser.parse_args()


def fetch_messages(client: WebClient, channel_id: str, keyword: str, days: int) -> List[Dict]:
    """
    conversations.history + conversations.replies でメッセージを取得し、
    キーワードフィルタ＋重複排除して返す。
    """
    oldest = (datetime.now() - timedelta(days=days)).timestamp()
    latest = datetime.now().timestamp()
    keyword_lower = keyword.lower()

    # conversations.history で期間内の全メッセージ取得
    all_channel_messages = []
    try:
        cursor = None
        while True:
            response = client.conversations_history(
                channel=channel_id,
                oldest=str(oldest),
                latest=str(latest),
                limit=200,
                cursor=cursor
            )
            if not response["ok"]:
                print(f"Error: {response.get('error', 'Unknown error')}", file=sys.stderr)
                sys.exit(1)

            all_channel_messages.extend(response.get("messages", []))

            if response.get("has_more") and response.get("response_metadata", {}).get("next_cursor"):
                cursor = response["response_metadata"]["next_cursor"]
                time.sleep(1.5)  # Tier 3
            else:
                break
    except SlackApiError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Fetched {len(all_channel_messages)} messages from channel history.")

    # キーワードフィルタ＋重複排除（親メッセージ＋スレッド返信）
    messages = []
    seen_texts = set()

    for msg in all_channel_messages:
        # 親メッセージのチェック
        text = msg.get("text", "")
        ts = msg.get("ts")
        if keyword_lower in text.lower():
            normalized_text = text.strip().lower()
            if normalized_text not in seen_texts:
                seen_texts.add(normalized_text)
                messages.append(msg)

        # スレッドがある場合は返信も検索
        if msg.get("reply_count", 0) > 0:
            try:
                reply_cursor = None
                while True:
                    reply_response = client.conversations_replies(
                        channel=channel_id,
                        ts=ts,
                        oldest=str(oldest),
                        latest=str(latest),
                        limit=200,
                        cursor=reply_cursor
                    )
                    if not reply_response["ok"]:
                        break

                    replies = reply_response.get("messages", [])
                    # 最初のページでは親メッセージ（index 0）をスキップ
                    for reply in (replies[1:] if reply_cursor is None else replies):
                        reply_text = reply.get("text", "")
                        if keyword_lower in reply_text.lower():
                            normalized_reply = reply_text.strip().lower()
                            if normalized_reply not in seen_texts:
                                seen_texts.add(normalized_reply)
                                messages.append(reply)

                    if reply_response.get("has_more") and reply_response.get("response_metadata", {}).get("next_cursor"):
                        reply_cursor = reply_response["response_metadata"]["next_cursor"]
                        time.sleep(1.5)  # Tier 3
                    else:
                        break

                time.sleep(1.5)  # Tier 3
            except SlackApiError as e:
                print(f"Warning: Failed to fetch replies for thread {ts}: {e}", file=sys.stderr)

    print(f"Found {len(messages)} messages containing the keyword.")
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

    print(f"Searching for messages containing '{args.keyword}' in channel {args.channel}...")
    print(f"Search period: last {args.days} days")

    messages = fetch_messages(client, args.channel, args.keyword, args.days)

    if not messages:
        print(f"\nNo messages found containing '{args.keyword}' in the specified period.")
        empty_result = format_output(args.channel, args.keyword, args.days, {}, 0)
        save_results(empty_result, args.output)
        sys.exit(0)

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