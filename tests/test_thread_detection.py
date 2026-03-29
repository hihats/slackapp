#!/usr/bin/env python3
"""
スレッド内メンションの検出をテストするスクリプト
問題の再現と修正の検証用
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone
from slack_sdk import WebClient

def test_thread_detection(token, channel_id, test_user_id):
    """スレッド検出のテストを実行"""
    client = WebClient(token=token)
    
    # 過去7日間のメッセージを取得
    oldest_time = (datetime.now(timezone.utc) - timedelta(days=7)).timestamp()
    
    print("=== メッセージ取得テスト ===")
    print(f"チャンネル: {channel_id}")
    print(f"対象ユーザー: {test_user_id}")
    print(f"期間: 過去7日間\n")
    
    try:
        # チャンネルの履歴を取得
        response = client.conversations_history(
            channel=channel_id,
            oldest=str(oldest_time),
            limit=100
        )
        
        if not response["ok"]:
            print("エラー: メッセージ取得に失敗")
            return
        
        messages = response.get("messages", [])
        print(f"取得メッセージ数: {len(messages)}\n")
        
        # スレッドを持つメッセージを分析
        thread_parents = []
        for msg in messages:
            # thread_tsとreply_countの存在を確認
            has_thread_ts = "thread_ts" in msg
            has_reply_count = "reply_count" in msg
            reply_count = msg.get("reply_count", 0)
            
            if has_thread_ts or has_reply_count or reply_count > 0:
                thread_parents.append({
                    "ts": msg["ts"],
                    "text": msg.get("text", "")[:100],
                    "has_thread_ts": has_thread_ts,
                    "has_reply_count": has_reply_count,
                    "reply_count": reply_count,
                    "thread_ts": msg.get("thread_ts", "なし")
                })
        
        print(f"=== スレッド関連メッセージ: {len(thread_parents)}件 ===")
        for i, parent in enumerate(thread_parents[:5], 1):  # 最初の5件のみ表示
            print(f"\n[{i}] ts: {parent['ts']}")
            print(f"  thread_ts存在: {parent['has_thread_ts']} (値: {parent['thread_ts']})")
            print(f"  reply_count存在: {parent['has_reply_count']} (値: {parent['reply_count']})")
            print(f"  テキスト: {parent['text']}")
            
            # 実際にスレッドを取得してみる
            if parent['reply_count'] > 0:
                print(f"  → スレッド内返信を取得中...")
                thread_response = client.conversations_replies(
                    channel=channel_id,
                    ts=parent['ts'],
                    limit=10
                )
                
                if thread_response["ok"]:
                    replies = thread_response.get("messages", [])
                    print(f"     スレッド内メッセージ数: {len(replies)}")
                    
                    # メンションを含むメッセージを探す
                    mention_pattern = f"<@{test_user_id}>"
                    mentions_in_thread = []
                    
                    for j, reply in enumerate(replies):
                        if mention_pattern in reply.get("text", ""):
                            mentions_in_thread.append({
                                "index": j,
                                "ts": reply["ts"],
                                "user": reply.get("user", ""),
                                "text": reply.get("text", "")[:100]
                            })
                    
                    if mentions_in_thread:
                        print(f"     ⚠️ スレッド内にメンション発見: {len(mentions_in_thread)}件")
                        for mention in mentions_in_thread:
                            print(f"        - [{mention['index']}] {mention['text']}")
        
        # 問題の診断
        print("\n=== 診断結果 ===")
        print("現在のコードの問題:")
        print("1. thread_tsはスレッド内の返信に存在（親メッセージには通常存在しない）")
        print("2. reply_countはスレッドの親メッセージに存在")
        print("3. 条件 'if \"thread_ts\" in message or \"reply_count\" in message:' は不適切")
        print("\n推奨修正:")
        print("- スレッドの親: reply_count > 0 で判定")
        print("- thread_tsフィールドは無視（返信メッセージの識別用）")
        
    except Exception as e:
        print(f"エラー: {e}")

if __name__ == "__main__":
    # 環境変数またはコマンドライン引数から設定を取得
    token = os.environ.get("SLACK_TOKEN", "")
    channel = os.environ.get("SLACK_CHANNEL", "")
    user = os.environ.get("SLACK_USER", "")
    
    if len(sys.argv) > 3:
        token = sys.argv[1]
        channel = sys.argv[2]
        user = sys.argv[3]
    
    if not all([token, channel, user]):
        print("使用方法:")
        print("  python test_thread_detection.py TOKEN CHANNEL_ID USER_ID")
        print("または環境変数を設定:")
        print("  export SLACK_TOKEN=xoxb-...")
        print("  export SLACK_CHANNEL=C...")
        print("  export SLACK_USER=U...")
        sys.exit(1)
    
    test_thread_detection(token, channel, user)