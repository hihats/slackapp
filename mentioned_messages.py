#!/usr/bin/env python3
"""
Slack Mentioned Messages Text Extractor

特定ユーザーへのメンションを含むメッセージを検索し、
本文のみをプレーンテキストで出力します。
Search APIを使用した高速検索に対応しています。
"""

import argparse
import sys
from datetime import datetime, timedelta
from typing import Dict, List

from slack_sdk import WebClient

from slack_search import SlackSearchError, build_query, search_all_messages
from slack_user import resolve_user_id


def parse_arguments():
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(
        description="特定ユーザーへのメンションを含むメッセージを検索し、本文テキストをファイル出力"
    )
    parser.add_argument("--token", required=True, help="Slack API トークン")
    parser.add_argument("--mentioned-user", required=True, help="メンション対象のユーザーIDまたは表示名（例: U12345ABC, hisahiro.tsukamoto）")
    parser.add_argument("--channel", default=None, help="チャンネルID（省略時は全チャンネル横断検索）")
    parser.add_argument("--days", type=int, default=30, help="検索する過去日数 (デフォルト: 30)")
    parser.add_argument("--output", required=True, help="出力テキストファイルパス")
    return parser.parse_args()


def fetch_messages(client: WebClient, user_id: str, days: int, channel_id: str = None) -> List[Dict]:
    """
    Search APIでメンションメッセージを検索し、重複排除して返す。
    ユーザーIDから <@U12345> 形式のメンション文字列を構築して検索する。
    """
    mention_keyword = f"<@{user_id}>"
    after_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    # build_query の keyword は .lower() されるためユーザーIDが壊れる。
    # extra 経由で渡すことで大文字を維持する。
    query = build_query(channel_id=channel_id, after_date=after_date, extra=mention_keyword)

    try:
        all_matches = search_all_messages(client, query, sort="timestamp", sort_dir="asc")
    except SlackSearchError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # 重複排除
    messages = []
    seen_texts = set()
    for match in all_matches:
        text = match.get("text", "")
        normalized_text = text.strip().lower()
        if normalized_text not in seen_texts:
            seen_texts.add(normalized_text)
            messages.append(match)

    print(f"\nSearch completed: {len(messages)} unique messages (from {len(all_matches)} total)")
    return messages


def extract_texts(messages: List[Dict]) -> List[str]:
    """メッセージリストから本文テキストのみを抽出する"""
    texts = []
    for message in messages:
        text = message.get("text", "").strip()
        if text:
            # 改行を含むメッセージは1行に結合（出力で1行1メッセージにするため）
            text = text.replace("\n", " ")
            texts.append(text)
    return texts


def save_as_text(texts: List[str], output_path: str):
    """テキストリストを1行1メッセージでファイルに保存"""
    with open(output_path, "w", encoding="utf-8") as f:
        for text in texts:
            f.write(text + "\n")
    print(f"\nResults saved to: {output_path}")


def main():
    args = parse_arguments()

    client = WebClient(token=args.token)

    user_id = resolve_user_id(client, args.mentioned_user)
    mention_keyword = f"<@{user_id}>"
    channel_info = f"channel {args.channel}" if args.channel else "all channels"
    print(f"Searching for messages mentioning '{mention_keyword}' in {channel_info}...")
    print(f"Search period: last {args.days} days")
    print("Using Search API for fast cross-message search (including threads)...")

    messages = fetch_messages(client, user_id, args.days, args.channel)

    if not messages:
        print(f"\nNo messages found mentioning '{mention_keyword}' in the specified period.")
        save_as_text([], args.output)
        sys.exit(0)

    texts = extract_texts(messages)
    print(f"\nExtracted {len(texts)} message texts.")

    save_as_text(texts, args.output)


if __name__ == "__main__":
    main()
