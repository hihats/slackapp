import os
import argparse
import json
import re
from datetime import datetime, timedelta
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import time
import random

def handle_rate_limit(func, *args, max_retries=5, base_delay=1, **kwargs):
    """レート制限に対応するためのラッパー関数"""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                if attempt == max_retries - 1:
                    print(f"最大再試行回数に達しました: {e}")
                    raise
                            # HTTP 429 Too Many Requestsの場合
                if e.response.status_code == 429:
                    retry_after = int(e.response.headers.get('Retry-After', 30))
                    print(f"レート制限に達しました。{retry_after:.2f}秒待機します... (試行 {attempt + 1}/{max_retries})")
                    time.sleep(retry_after)

            else:
                raise
    
    return None

def parse_arguments():
    parser = argparse.ArgumentParser(
        description='特定のメンションを含むメッセージで、メンション先の人が何もリアクションや返信をしていないメッセージを取得します。',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--token', type=str, required=True, help='Slack APIトークン')
    parser.add_argument('--mentioned-user', type=str, required=True, help='メンション先ユーザーのID')
    parser.add_argument('--channel', type=str, help='検索対象のチャンネルID（指定しない場合は全チャンネル）')
    parser.add_argument('--days', type=int, default=30, help='遡って検索する日数（デフォルト: 30日）')
    parser.add_argument('--output', type=str, default='unanswered_mentions.json', help='出力ファイル名（デフォルト: unanswered_mentions.json）')
    return parser.parse_args()

def load_inactive_channels_from_json():
    """output/inactive_channels.jsonから非アクティブチャンネルIDのセットを読み込み"""
    inactive_json_path = os.path.join('/app/output', 'inactive_channels.json') if os.path.exists('/app/output') else 'inactive_channels.json'
    
    try:
        with open(inactive_json_path, 'r', encoding='utf-8') as f:
            inactive_data = json.load(f)
        
        inactive_channels = inactive_data.get("inactive_channels", [])
        # セット内包表記を使用
        inactive_channel_ids = {ch["id"] for ch in inactive_channels}
        
        print(f"非アクティブチャンネル {len(inactive_channel_ids)} 個を除外対象として読み込みました")
        return inactive_channel_ids
    
    except FileNotFoundError:
        print("inactive_channels.jsonが見つかりません（非アクティブチャンネル除外をスキップ）")
        return set()
    except json.JSONDecodeError as e:
        print(f"inactive_channels.json読み込みエラー: {e} （非アクティブチャンネル除外をスキップ）")
        return set()
    except Exception as e:
        print(f"非アクティブチャンネル読み込みエラー: {e} （非アクティブチャンネル除外をスキップ）")
        return set()

def load_all_channels_from_json(json_file_path):
    """all_channels.jsonからチャンネルリストを読み込み"""
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            channel_data = json.load(f)
        
        channels = channel_data.get("channels", [])
        print(f"JSONファイルから {len(channels)} 個のチャンネルを読み込みました")
        print(f"最終更新日時: {channel_data.get('last_updated', '不明')}")
        
        # 非アクティブチャンネルIDを読み込み
        inactive_channel_ids = load_inactive_channels_from_json()
        
        # リスト内包表記を使用してチャンネルを変換（非アクティブチャンネル除外）
        converted_channels = [
            {
                "id": ch["id"],
                "name": ch.get("name", ""),
                "is_channel": ch.get("is_channel", False),
                "is_group": ch.get("is_group", False),
                "is_im": ch.get("is_im", False),
                "is_mpim": ch.get("is_mpim", False),
                "is_private": ch.get("is_private", False),
                "is_member": ch.get("is_member", False),
                "num_members": ch.get("num_members", 0)
            }
            for ch in channels
            if ch["id"] not in inactive_channel_ids
        ]
        
        excluded_count = len(channels) - len(converted_channels)
        if excluded_count > 0:
            print(f"非アクティブチャンネル {excluded_count} 個を除外しました")
        print(f"処理対象チャンネル: {len(converted_channels)} 個")
        
        return converted_channels
    
    except FileNotFoundError:
        print(f"エラー: {json_file_path} が見つかりません")
        print("先に get_all_channels.py を実行してチャンネルリストを作成してください:")
        print(f"docker run --volume $PWD:/app slackapp get_all_channels.py --token $SLACK_TOKEN --user {{args.mentioned_user}}")
        return []
    except json.JSONDecodeError as e:
        print(f"JSONファイル読み込みエラー: {e}")
        return []
    except Exception as e:
        print(f"チャンネル読み込みエラー: {e}")
        return []

def get_channel_info(client, channel_id):
    """チャンネル情報を取得"""
    try:
        response = handle_rate_limit(
            client.conversations_info,
            channel=channel_id
        )
        if response and response["ok"]:
            return response["channel"]
    except SlackApiError as e:
        print(f"チャンネル情報取得エラー ({channel_id}): {e}")
    
    return None

def get_messages_with_mentions(client, channel_id, mentioned_user_id, days_ago):
    """指定したチャンネルから特定のユーザーへのメンションを含むメッセージを取得（スレッド内も含む）"""
    all_messages = []
    
    # 検索対象の期間を設定
    oldest_time = (datetime.now() - timedelta(days=days_ago)).timestamp()
    mention_pattern = f"<@{mentioned_user_id}>"
    
    try:
        cursor = None
        while True:
            # チャンネルの履歴を取得
            response = handle_rate_limit(
                client.conversations_history,
                channel=channel_id,
                oldest=str(oldest_time),
                limit=200,
                cursor=cursor
            )
            
            if not response or not response["ok"]:
                break
            
            messages = response.get("messages", [])
            if not messages:
                break
            
            # メンションを含むメッセージを抽出（リスト内包表記を使用）
            mention_messages = [
                message for message in messages
                if mention_pattern in message.get("text", "")
            ]
            all_messages.extend(mention_messages)
            
            # スレッドのあるメッセージに対して、スレッド内のメンションもチェック
            for message in messages:
                if "thread_ts" in message or "reply_count" in message:
                    thread_mentions = get_thread_mentions(client, channel_id, message["ts"], mention_pattern, oldest_time)
                    all_messages.extend(thread_mentions)
            
            # 次のページがあるかチェック
            response_metadata = response.get("response_metadata", {})
            next_cursor = response_metadata.get("next_cursor")
            
            if not next_cursor:
                break
            
            cursor = next_cursor
            time.sleep(10)
        
        return all_messages
    
    except SlackApiError as e:
        print(f"メッセージ取得エラー ({channel_id}): {e}")
        return []

def get_thread_mentions(client, channel_id, thread_ts, mention_pattern, oldest_time):
    """スレッド内のメンションを含むメッセージを取得"""
    thread_mentions = []
    
    try:
        response = handle_rate_limit(
            client.conversations_replies,
            channel=channel_id,
            ts=thread_ts,
            limit=200
        )
        
        if response and response["ok"]:
            replies = response.get("messages", [])
            # 最初のメッセージは元のメッセージなのでスキップ
            for reply in replies[1:]:
                # 期間内かつメンションを含むメッセージを抽出
                if (float(reply["ts"]) >= oldest_time and 
                    mention_pattern in reply.get("text", "")):
                    thread_mentions.append(reply)
    
    except SlackApiError as e:
        print(f"スレッド取得エラー ({channel_id}, {thread_ts}): {e}")
    
    time.sleep(5)  # スレッド取得のレート制限対策
    return thread_mentions

def check_user_reactions_and_replies(client, channel_id, message, mentioned_user_id):
    """メッセージに対してメンションされたユーザーがリアクションや返信をしているか確認"""
    message_ts = message["ts"]
    
    # 1. リアクションをチェック
    reactions = message.get("reactions", [])
    for reaction in reactions:
        if mentioned_user_id in reaction.get("users", []):
            return True, "reaction", reaction["name"]
    
    # 2. スレッドの返信をチェック
    try:
        if "thread_ts" in message or "reply_count" in message:
            # スレッドの返信を取得
            thread_response = handle_rate_limit(
                client.conversations_replies,
                channel=channel_id,
                ts=message_ts,
                limit=200
            )
            
            if thread_response and thread_response["ok"]:
                replies = thread_response.get("messages", [])
                # 最初のメッセージは元のメッセージなのでスキップ
                for reply in replies[1:]:
                    if reply.get("user") == mentioned_user_id:
                        return True, "reply", reply.get("text", "")[:100]
        
        # 3. 直後の返信もチェック（スレッドでない場合）
        # 元のメッセージの直後24時間以内にメンションされたユーザーからの投稿があるかチェック
        message_time = float(message_ts)
        one_day_later = message_time + 3600 * 24  # 24時間後
        
        recent_response = handle_rate_limit(
            client.conversations_history,
            channel=channel_id,
            oldest=str(message_time),
            latest=str(one_day_later),
            limit=50
        )
        
        if recent_response and recent_response["ok"]:
            recent_messages = recent_response.get("messages", [])
            for recent_msg in recent_messages:
                if (recent_msg.get("user") == mentioned_user_id and 
                    float(recent_msg["ts"]) > message_time):
                    return True, "followup", recent_msg.get("text", "")[:100]
    
    except SlackApiError as e:
        print(f"返信チェックエラー: {e}")
    
    return False, None, None

def get_user_info(client, user_id):
    """ユーザー情報を取得"""
    try:
        response = handle_rate_limit(
            client.users_info,
            user=user_id
        )
        if response and response["ok"]:
            return response["user"]
    except SlackApiError as e:
        print(f"ユーザー情報取得エラー: {e}")
    
    return None

def format_message_data(message, channel_id, channel_name, mentioned_user_info, author_info):
    """メッセージデータをフォーマット"""
    return {
        "channel_id": channel_id,
        "channel_name": channel_name or channel_id,
        "timestamp": message["ts"],
        "datetime": datetime.fromtimestamp(float(message["ts"])).strftime("%Y-%m-%d %H:%M:%S"),
        "text": message.get("text", ""),
        "author": {
            "id": message.get("user", ""),
            "name": author_info.get("display_name", "") if author_info else "",
            "real_name": author_info.get("real_name", "") if author_info else ""
        },
        "mentioned_user": {
            "id": mentioned_user_info.get("id", "") if mentioned_user_info else "",
            "name": mentioned_user_info.get("display_name", "") if mentioned_user_info else "",
            "real_name": mentioned_user_info.get("real_name", "") if mentioned_user_info else ""
        },
        "permalink": f"https://slack.com/app_redirect?channel={channel_id}&message_ts={message['ts']}"
    }

def save_to_json(data, filename):
    """JSONファイルに保存"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    # 実行開始時刻を記録
    script_start_time = time.time()
    
    args = parse_arguments()
    print(f"設定: {args}")
    
    # Slack APIクライアントを初期化
    client = WebClient(token=args.token)
    
    # メンションされたユーザーの情報を取得
    mentioned_user_info = get_user_info(client, args.mentioned_user)
    if not mentioned_user_info:
        print(f"ユーザーID {args.mentioned_user} の情報が取得できませんでした")
        return
    
    mentioned_user_name = mentioned_user_info.get("display_name") or mentioned_user_info.get("real_name", "")
    print(f"メンションされたユーザー: {mentioned_user_name} ({args.mentioned_user})")
    
    # チャンネルリストを取得
    if args.channel:
        # 特定のチャンネルのみ
        channel_info = get_channel_info(client, args.channel)
        if not channel_info:
            print(f"チャンネル {args.channel} の情報が取得できませんでした")
            return
        channels = [channel_info]
        print(f"対象チャンネル: #{channel_info.get('name', args.channel)}")
    else:
        # 全チャンネル（JSONファイルから読み込み）
        print("全チャンネルをJSONファイルから読み込み中...")
        json_file_path = os.path.join('/app/output', 'all_channels.json') if os.path.exists('/app/output') else 'all_channels.json'
        channels = load_all_channels_from_json(json_file_path)
        if not channels:
            print("チャンネルが見つかりませんでした")
            print("先に get_all_channels.py を実行してチャンネルリストを作成してください")
            return
        print(f"対象チャンネル数: {len(channels)}")
    
    # 各チャンネルでメンション検索
    all_unanswered_messages = []
    total_mentions = 0
    
    for i, channel in enumerate(channels):
        channel_id = channel["id"]
        channel_name = f"#{channel.get('name', channel_id)}"
        
        
        # メンション付きメッセージを取得
        messages_with_mentions = get_messages_with_mentions(
            client, channel_id, args.mentioned_user, args.days
        )
        
        if not messages_with_mentions:
            continue
        
        print(f"\n[{i+1}/{len(channels)}] {channel_name} に {len(messages_with_mentions)}件のメンション付きメッセージが見つかりました")
        total_mentions += len(messages_with_mentions)
        
        # 各メッセージの反応をチェック
        channel_unanswered = []
        for j, message in enumerate(messages_with_mentions):
            if j % 10 == 0 and j > 0:
                print(f"    進捗: {j}/{len(messages_with_mentions)}")
            
            # ユーザーが反応しているかチェック
            has_response, response_type, response_content = check_user_reactions_and_replies(
                client, channel_id, message, args.mentioned_user
            )
            
            if not has_response:
                # 投稿者の情報を取得
                author_info = get_user_info(client, message.get("user", ""))
                
                # 未回答メッセージとして記録
                formatted_message = format_message_data(
                    message, channel_id, channel_name, mentioned_user_info, author_info
                )
                channel_unanswered.append(formatted_message)
            
            time.sleep(10)  # APIレート制限対策
        
        all_unanswered_messages.extend(channel_unanswered)
        print(f"  未回答メッセージ: {len(channel_unanswered)}件")
    
    # 結果を保存
    if all_unanswered_messages:
        output_path = os.path.join('/app/output', args.output) if os.path.exists('/app/output') else args.output
        
        # タイムスタンプでソート（新しい順）
        all_unanswered_messages.sort(key=lambda x: float(x['timestamp']), reverse=True)
        
        save_to_json(all_unanswered_messages, output_path)
        
        print(f"\n=== 全体結果 ===")
        print(f"検索対象チャンネル数: {len(channels)}")
        print(f"メンション付きメッセージ総数: {total_mentions}")
        print(f"未回答メッセージ数: {len(all_unanswered_messages)}")
        if total_mentions > 0:
            print(f"回答率: {((total_mentions - len(all_unanswered_messages)) / total_mentions * 100):.1f}%")
        print(f"結果を {output_path} に保存しました")
        
        # チャンネル別統計
        from collections import Counter
        channel_stats = Counter([msg["channel_name"] for msg in all_unanswered_messages])
        print(f"\n=== チャンネル別未回答メッセージ数 ===")
        for channel, count in channel_stats.most_common(10):
            print(f"{channel}: {count}件")
        
        # 最近の未回答メッセージを表示
        print(f"\n=== 最近の未回答メッセージ (上位5件) ===")
        for message in all_unanswered_messages[:5]:
            print(f"[{message['datetime']}] {message['channel_name']}")
            print(f"  投稿者: {message['author']['name']} ({message['author']['id']})")
            print(f"  テキスト: {message['text'][:200]}{'...' if len(message['text']) > 200 else ''}")
            print(f"  リンク: {message['permalink']}")
            print()
    else:
        print(f"\n全てのメンションに対して {mentioned_user_name} が何らかの反応をしています！")
    
    # 実行時間を表示
    total_time = time.time() - script_start_time
    print(f"\n=== 実行完了 ===")
    print(f"総実行時間: {total_time/60:.1f}分 ({total_time:.2f}秒)")

if __name__ == "__main__":
    main()