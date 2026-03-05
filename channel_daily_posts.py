import os
import argparse
import json
import csv
from datetime import datetime, timedelta
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import time

def parse_arguments():
    parser = argparse.ArgumentParser(description='特定のチャンネルの指定した日付の投稿とスレッドを全て取得します')
    parser.add_argument('--channel', type=str, required=True, help='チャンネルID')
    parser.add_argument('--date', type=str, help='取得する日付 (YYYY-MM-DD形式)')
    parser.add_argument('--days', type=int, help='今日からN日前までの期間を取得')
    parser.add_argument('--output', type=str, default='channel_daily_posts.json', help='出力ファイル名（デフォルト: channel_daily_posts.json）')
    parser.add_argument('--format', type=str, choices=['json', 'csv'], default='json', help='出力形式（json または csv）')
    parser.add_argument('--include-threads', action='store_true', default=True, help='スレッドも含めて取得する')
    parser.add_argument('--timezone', type=str, default='Asia/Tokyo', help='タイムゾーン（デフォルト: Asia/Tokyo）')
    return parser.parse_args()

def get_slack_token():
    """環境変数からSlackトークンを取得"""
    token = os.environ.get('SLACK_TOKEN')
    if not token:
        print("エラー: 環境変数SLACK_TOKENが設定されていません")
        print("以下のコマンドでトークンを設定してください:")
        print("export SLACK_TOKEN='your-slack-token'")
        return None
    return token

def parse_date(date_str):
    """日付文字列をパースして開始・終了タイムスタンプを返す"""
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d')
        start_time = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        return start_time.timestamp(), end_time.timestamp()
    except ValueError:
        print(f"エラー: 日付形式が正しくありません。YYYY-MM-DD形式で入力してください: {date_str}")
        return None, None

def parse_days(days):
    """N日前から今日までの開始・終了タイムスタンプを返す"""
    today = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
    start = (datetime.now() - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), today.timestamp()


def get_channel_info(client, channel_id):
    """チャンネル情報を取得"""
    try:
        response = client.conversations_info(channel=channel_id)
        if response["ok"]:
            return response["channel"]
    except SlackApiError as e:
        print(f"チャンネル情報取得エラー: {e}")
    return None

def get_user_info(client, user_id):
    """ユーザー情報を取得"""
    try:
        response = client.users_info(user=user_id)
        if response["ok"]:
            return response["user"]
    except SlackApiError as e:
        print(f"ユーザー情報取得エラー: {e}")
    return None

def get_channel_messages(client, channel_id, oldest, latest):
    """チャンネルのメッセージを取得"""
    messages = []
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
                print(f"メッセージ取得エラー: {response.get('error', 'Unknown error')}")
                break
            
            batch_messages = response.get("messages", [])
            messages.extend(batch_messages)
            
            # 次のページがあるかチェック
            if response.get("has_more") and response.get("response_metadata", {}).get("next_cursor"):
                cursor = response["response_metadata"]["next_cursor"]
                time.sleep(0.5)  # APIレート制限対策
            else:
                break
                
    except SlackApiError as e:
        print(f"メッセージ取得エラー: {e}")
    
    return messages

def get_thread_replies(client, channel_id, thread_ts):
    """スレッドの返信を取得"""
    replies = []
    try:
        cursor = None
        while True:
            response = client.conversations_replies(
                channel=channel_id,
                ts=thread_ts,
                limit=200,
                cursor=cursor
            )
            
            if not response["ok"]:
                print(f"スレッド取得エラー: {response.get('error', 'Unknown error')}")
                break
            
            batch_replies = response.get("messages", [])
            # 最初のメッセージ（親メッセージ）は除外
            if batch_replies:
                replies.extend(batch_replies[1:] if cursor is None else batch_replies)
            
            # 次のページがあるかチェック
            if response.get("has_more") and response.get("response_metadata", {}).get("next_cursor"):
                cursor = response["response_metadata"]["next_cursor"]
                time.sleep(0.5)  # APIレート制限対策
            else:
                break
                
    except SlackApiError as e:
        print(f"スレッド取得エラー: {e}")
    
    return replies

def format_message_data(message, channel_info, user_cache, message_type="message"):
    """メッセージデータをフォーマット"""
    user_id = message.get("user", "")
    user_info = user_cache.get(user_id)
    
    return {
        "type": message_type,
        "channel_id": channel_info["id"] if channel_info else "",
        "channel_name": channel_info["name"] if channel_info else "",
        "timestamp": message["ts"],
        "datetime": datetime.fromtimestamp(float(message["ts"])).strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": user_id,
        "user_name": user_info["name"] if user_info else "",
        "user_display_name": user_info.get("profile", {}).get("display_name", "") if user_info else "",
        "text": message.get("text", ""),
        "thread_ts": message.get("thread_ts"),
        "reply_count": message.get("reply_count", 0),
        "reactions": message.get("reactions", []),
        "attachments": message.get("attachments", []),
        "files": message.get("files", []),
        "blocks": message.get("blocks", []),
        "permalink": f"https://slack.com/app_redirect?channel={channel_info['id'] if channel_info else ''}&message_ts={message['ts']}"
    }

def save_to_json(data, filename):
    """JSONファイルに保存"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_to_csv(data, filename):
    """CSVファイルに保存"""
    if not data:
        return
    
    # 親投稿とスレッド返信を分けて保存
    parent_messages = [item for item in data if item["type"] == "message"]
    thread_replies = [item for item in data if item["type"] == "thread_reply"]
    
    # 複雑なフィールドを文字列に変換
    def convert_for_csv(items):
        csv_items = []
        for item in items:
            csv_item = item.copy()
            csv_item['reactions'] = json.dumps(item['reactions'], ensure_ascii=False)
            csv_item['attachments'] = json.dumps(item['attachments'], ensure_ascii=False)
            csv_item['files'] = json.dumps(item['files'], ensure_ascii=False)
            csv_item['blocks'] = json.dumps(item['blocks'], ensure_ascii=False)
            csv_items.append(csv_item)
        return csv_items
    
    # 親投稿CSV
    if parent_messages:
        messages_filename = filename.replace('.csv', '_messages.csv')
        csv_messages = convert_for_csv(parent_messages)
        with open(messages_filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=csv_messages[0].keys())
            writer.writeheader()
            writer.writerows(csv_messages)
        print(f"親投稿を {messages_filename} に保存しました")
    
    # スレッド返信CSV
    if thread_replies:
        replies_filename = filename.replace('.csv', '_thread_replies.csv')
        csv_replies = convert_for_csv(thread_replies)
        with open(replies_filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=csv_replies[0].keys())
            writer.writeheader()
            writer.writerows(csv_replies)
        print(f"スレッド返信を {replies_filename} に保存しました")

def main():
    args = parse_arguments()
    
    # Slackトークンを取得
    token = get_slack_token()
    if not token:
        return
    
    # --date と --days のバリデーション
    if args.date and args.days:
        print("エラー: --date と --days は同時に指定できません")
        return
    if not args.date and args.days is None:
        print("エラー: --date または --days のどちらかを指定してください")
        return

    # 期間を算出
    if args.days is not None:
        oldest_ts, latest_ts = parse_days(args.days)
        start_date = (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')
        period_label = f"{start_date} ~ {end_date}（{args.days}日間）"
    else:
        oldest_ts, latest_ts = parse_date(args.date)
        if oldest_ts is None or latest_ts is None:
            return
        period_label = args.date

    # Slack APIクライアントを初期化
    client = WebClient(token=token)

    # チャンネル情報を取得
    print("チャンネル情報を取得中...")
    channel_info = get_channel_info(client, args.channel)
    if not channel_info:
        print("チャンネル情報を取得できませんでした")
        return

    print(f"チャンネル: #{channel_info['name']} ({args.channel})")
    print(f"取得期間: {period_label}")
    
    # メッセージを取得
    print("メッセージを取得中...")
    messages = get_channel_messages(client, args.channel, oldest_ts, latest_ts)
    
    if not messages:
        print("指定された日付のメッセージが見つかりませんでした")
        return
    
    print(f"{len(messages)}件のメッセージが見つかりました")
    
    # ユーザー情報をキャッシュ
    user_cache = {}
    all_data = []
    
    # 親メッセージを処理
    parent_messages = []
    thread_messages = []
    
    for message in messages:
        user_id = message.get("user", "")
        if user_id and user_id not in user_cache:
            user_cache[user_id] = get_user_info(client, user_id)
        
        # メッセージデータをフォーマット
        formatted_message = format_message_data(message, channel_info, user_cache, "message")
        all_data.append(formatted_message)
        
        # スレッドがある場合
        if args.include_threads and message.get("reply_count", 0) > 0:
            thread_ts = message.get("thread_ts") or message["ts"]
            parent_messages.append(message)
            
            print(f"スレッドを取得中... ({len(parent_messages)}/{len([m for m in messages if m.get('reply_count', 0) > 0])})")
            
            # スレッドの返信を取得
            replies = get_thread_replies(client, args.channel, thread_ts)
            
            for reply in replies:
                reply_user_id = reply.get("user", "")
                if reply_user_id and reply_user_id not in user_cache:
                    user_cache[reply_user_id] = get_user_info(client, reply_user_id)
                
                formatted_reply = format_message_data(reply, channel_info, user_cache, "thread_reply")
                all_data.append(formatted_reply)
                thread_messages.append(reply)
            
            time.sleep(0.5)  # APIレート制限対策
    
    # 結果を保存
    if all_data:
        output_path = os.path.join('/app/output', args.output) if os.path.exists('/app/output') else args.output
        
        # タイムスタンプでソート
        all_data.sort(key=lambda x: float(x['timestamp']))
        
        if args.format == 'json':
            save_to_json(all_data, output_path)
            print(f"結果を {output_path} に保存しました")
        else:
            save_to_csv(all_data, output_path)
        
        # 統計情報を表示
        parent_count = len([item for item in all_data if item["type"] == "message"])
        thread_count = len([item for item in all_data if item["type"] == "thread_reply"])
        
        print(f"\n=== 取得結果 ===")
        print(f"親投稿数: {parent_count}")
        print(f"スレッド返信数: {thread_count}")
        print(f"合計: {len(all_data)}件")
        
        # 投稿者別の統計
        from collections import Counter
        user_stats = Counter([item["user_display_name"] or item["user_name"] for item in all_data if item["user_name"]])
        print(f"\n=== 投稿者別統計 ===")
        for user, count in user_stats.most_common(10):
            print(f"{user}: {count}件")
        
        # 時間帯別の統計
        hour_stats = Counter([item["datetime"].split()[1].split(':')[0] for item in all_data])
        print(f"\n=== 時間帯別統計 ===")
        for hour, count in sorted(hour_stats.items()):
            print(f"{hour}:00-{hour}:59: {count}件")
    else:
        print("データが見つかりませんでした")

if __name__ == "__main__":
    main()