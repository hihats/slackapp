import os
import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import time

from slack_conversations import fetch_all_thread_replies, fetch_channel_history, fetch_thread_replies
from slack_search import build_query, handle_rate_limit, search_messages

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
    parser.add_argument('--use-search-api', action='store_true', help='search.messages APIを使用して高速検索（search:readスコープが必要）')
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

def get_channels_with_mentions_from_search(client, mentioned_user_id, days_ago, channel_id=None):
    """search.messages APIを使用してメンションがあるチャンネルIDのセットを取得"""
    channels_with_mentions = set()

    after_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    query = build_query(
        channel_id=channel_id,
        after_date=after_date,
        extra=f"<@{mentioned_user_id}>",
    )
    print(f"検索クエリ: {query}")

    try:
        for matches in search_messages(client, query, sort="timestamp", sort_dir="desc"):
            if not matches:
                break
            print(f"  {len(matches)}件のメッセージを取得")
            channels_with_mentions.update(
                msg["channel"]["id"] for msg in matches
                if msg.get("channel", {}).get("id")
            )
    except Exception as e:
        print(f"検索APIエラー: {e}")
        return set()

    print(f"メンションが見つかったチャンネル数: {len(channels_with_mentions)}")
    return channels_with_mentions

def get_messages_with_mentions(client, channel_id, mentioned_user_id, days_ago):
    """指定したチャンネルから特定のユーザーへのメンションを含むメッセージを取得（スレッド内も含む）"""
    all_messages = []

    oldest_time = (datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp()
    mention_pattern = f"<@{mentioned_user_id}>"

    try:
        for messages in fetch_channel_history(client, channel_id, oldest=oldest_time):
            if not messages:
                break

            # メンションを含むメッセージを抽出
            mention_messages = [
                message for message in messages
                if mention_pattern in message.get("text", "")
            ]
            all_messages.extend(mention_messages)

            # スレッドのあるメッセージに対して、スレッド内のメンションもチェック
            threaded_messages = [
                message for message in messages
                if message.get("reply_count", 0) > 0
            ]
            thread_mentions = [
                mention
                for message in threaded_messages
                for mention in get_thread_mentions(client, channel_id, message["ts"], mention_pattern, oldest_time)
            ]
            all_messages.extend(thread_mentions)

        return all_messages

    except SlackApiError as e:
        print(f"メッセージ取得エラー ({channel_id}): {e}")
        return []

def get_thread_mentions(client, channel_id, thread_ts, mention_pattern, oldest_time):
    """スレッド内のメンションを含むメッセージを取得"""
    thread_mentions = []

    try:
        for replies in fetch_thread_replies(client, channel_id, thread_ts, skip_parent=False):
            thread_mentions.extend([
                reply for reply in replies
                if mention_pattern in reply.get("text", "") and "thread_ts" in reply
            ])

    except SlackApiError as e:
        print(f"スレッド取得エラー ({channel_id}, {thread_ts}): {e}")

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
        # スレッドの親メッセージの場合、またはスレッド内の返信の場合
        thread_ts_to_check = None
        if message.get("reply_count", 0) > 0:
            # これはスレッドの親メッセージ
            thread_ts_to_check = message_ts
        elif "thread_ts" in message:
            # これはスレッド内の返信
            thread_ts_to_check = message["thread_ts"]
        
        if thread_ts_to_check:
            print(f"[DEBUG] スレッド返信チェック開始: thread_ts={thread_ts_to_check}, channel={channel_id}")
            print(f"[DEBUG] message type: {'parent' if message.get('reply_count', 0) > 0 else 'reply'}")
            
            # スレッドの返信を取得
            replies = fetch_all_thread_replies(client, channel_id, thread_ts_to_check, skip_parent=False)
            print(f"[DEBUG] スレッド内メッセージ数: {len(replies)}")

            # 最初のメッセージは元のメッセージなのでスキップ
            for i, reply in enumerate(replies[1:], 1):
                reply_user = reply.get("user", "")
                reply_text = reply.get("text", "")[:50]
                print(f"[DEBUG] 返信{i}: user={reply_user}")
                print(f"[DEBUG] 返信{i}テキスト: {reply_text}...")
                print(f"[DEBUG] 対象ユーザー({mentioned_user_id})と一致? {reply_user == mentioned_user_id}")

                if reply.get("user") == mentioned_user_id:
                    print(f"[DEBUG] ✅ スレッド内返信を発見!")
                    return True, "reply", reply.get("text", "")[:100]

            print(f"[DEBUG] ❌ スレッド内に対象ユーザーの返信なし")
        
        # 3. 直後の返信もチェック（スレッドでない場合）
        # 元のメッセージの直後24時間以内にメンションされたユーザーからの投稿があるかチェック
        message_time = float(message_ts)
        one_day_later = message_time + 3600 * 24  # 24時間後
        
        for recent_messages in fetch_channel_history(client, channel_id, oldest=message_time, latest=one_day_later, limit=50):
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

def initialize_client(token):
    """Slack APIクライアントを初期化"""
    return WebClient(token=token)

def get_target_channels(client, channel_id):
    """検索対象のチャンネルリストを取得"""
    if channel_id:
        # 特定のチャンネルのみ
        channel_info = get_channel_info(client, channel_id)
        if not channel_info:
            print(f"チャンネル {channel_id} の情報が取得できませんでした")
            return None
        channels = [channel_info]
        print(f"対象チャンネル: #{channel_info.get('name', channel_id)}")
    else:
        # 全チャンネル（JSONファイルから読み込み）
        print("全チャンネルをJSONファイルから読み込み中...")
        json_file_path = os.path.join('/app/output', 'all_channels.json') if os.path.exists('/app/output') else 'all_channels.json'
        channels = load_all_channels_from_json(json_file_path)
        if not channels:
            print("チャンネルが見つかりませんでした")
            print("先に get_all_channels.py を実行してチャンネルリストを作成してください")
            return None
        print(f"対象チャンネル数: {len(channels)}")
    
    return channels

def search_mentions_with_api(client, mentioned_user_id, days, channel_id, mentioned_user_info):
    """search.messages APIを使用してメンションを検索し、未回答メッセージを抽出"""
    print("\n=== search.messages APIを使用した検索モード ===")
    
    # Step 1: Search APIでメンションがあるチャンネルを発見
    channels_with_mentions = get_channels_with_mentions_from_search(
        client, 
        mentioned_user_id, 
        days,
        channel_id  # 特定チャンネルが指定されていればそれを使用
    )
    
    if not channels_with_mentions:
        print("メンションが見つかったチャンネルがありません")
        return [], 0
    
    print(f"メンションが見つかったチャンネル: {len(channels_with_mentions)}個")
    
    # Step 2: 各チャンネルでチャンネル情報を取得し、従来メソッドでメッセージを取得
    channels = []
    for ch_id in channels_with_mentions:
        channel_info = get_channel_info(client, ch_id)
        if channel_info:
            channels.append(channel_info)
        else:
            # チャンネル情報が取得できない場合は最小限の情報で作成
            channels.append({
                "id": ch_id,
                "name": ch_id,
                "is_channel": True,
                "is_member": True
            })
    
    # Step 3: 従来の検索メソッドを使用してメッセージを詳細取得
    return search_mentions_by_channel(client, channels, mentioned_user_id, days, mentioned_user_info)

def search_mentions_by_channel(client, channels, mentioned_user_id, days, mentioned_user_info):
    """チャンネルごとにメンションを検索し、未回答メッセージを抽出"""
    print("\n=== 従来の検索モード（チャンネルごと） ===")
    
    all_unanswered_messages = []
    total_mentions = 0
    
    for i, channel in enumerate(channels):
        channel_id = channel["id"]
        channel_name = f"#{channel.get('name', channel_id)}"
        
        # メンション付きメッセージを取得
        messages_with_mentions = get_messages_with_mentions(
            client, channel_id, mentioned_user_id, days
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
            has_response, _, _ = check_user_reactions_and_replies(
                client, channel_id, message, mentioned_user_id
            )
            
            if not has_response:
                # 投稿者の情報を取得
                author_info = get_user_info(client, message.get("user", ""))
                
                # 未回答メッセージとして記録
                formatted_message = format_message_data(
                    message, channel_id, channel_name, mentioned_user_info, author_info
                )
                channel_unanswered.append(formatted_message)
            
            time.sleep(3)  # conversations.list APIのレート制限対策（Tier 2: 20リクエスト/分）
        
        all_unanswered_messages.extend(channel_unanswered)
        print(f"  未回答メッセージ: {len(channel_unanswered)}件")
    
    return all_unanswered_messages, total_mentions

def print_results(all_unanswered_messages, total_mentions, channels, mentioned_user_name, use_search_api):
    """結果の統計情報を出力"""
    if all_unanswered_messages:
        print(f"\n=== 全体結果 ===")
        if not use_search_api and channels:
            print(f"検索対象チャンネル数: {len(channels)}")
        print(f"メンション付きメッセージ総数: {total_mentions}")
        print(f"未回答メッセージ数: {len(all_unanswered_messages)}")
        if total_mentions > 0:
            print(f"回答率: {((total_mentions - len(all_unanswered_messages)) / total_mentions * 100):.1f}%")
        
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

def save_results(all_unanswered_messages, output_filename):
    """結果をJSONファイルに保存"""
    if all_unanswered_messages:
        output_path = os.path.join('/app/output', output_filename) if os.path.exists('/app/output') else output_filename
        
        # タイムスタンプでソート（新しい順）
        all_unanswered_messages.sort(key=lambda x: float(x['timestamp']), reverse=True)
        
        save_to_json(all_unanswered_messages, output_path)
        print(f"結果を {output_path} に保存しました")
        
        return output_path
    return None

def main():
    """メイン関数 - オーケストレーションのみを担当"""
    # 実行開始時刻を記録
    script_start_time = time.time()
    
    # 引数を解析
    args = parse_arguments()
    print(f"設定: {args}")
    
    # Slack APIクライアントを初期化
    client = initialize_client(args.token)
    
    # メンションされたユーザーの情報を取得
    mentioned_user_info = get_user_info(client, args.mentioned_user)
    if not mentioned_user_info:
        print(f"ユーザーID {args.mentioned_user} の情報が取得できませんでした")
        return
    
    mentioned_user_name = mentioned_user_info.get("display_name") or mentioned_user_info.get("real_name", "")
    print(f"メンションされたユーザー: {mentioned_user_name} ({args.mentioned_user})")
    
    # メンション検索を実行
    if args.use_search_api:
        # search.messages APIを使用（all_channels.json不要）
        all_unanswered_messages, total_mentions = search_mentions_with_api(
            client, args.mentioned_user, args.days, args.channel, mentioned_user_info
        )
        channels = None  # Search API使用時は不要
    else:
        # 従来のチャンネルごとの検索（all_channels.json必要）
        channels = get_target_channels(client, args.channel)
        if channels is None:
            return
        all_unanswered_messages, total_mentions = search_mentions_by_channel(
            client, channels, args.mentioned_user, args.days, mentioned_user_info
        )
    
    # 結果を保存
    output_path = save_results(all_unanswered_messages, args.output)
    
    # 結果を表示
    print_results(
        all_unanswered_messages, 
        total_mentions, 
        channels, 
        mentioned_user_name,
        args.use_search_api
    )
    
    # 実行時間を表示
    total_time = time.time() - script_start_time
    print(f"\n=== 実行完了 ===")
    print(f"総実行時間: {total_time/60:.1f}分 ({total_time:.2f}秒)")

if __name__ == "__main__":
    main()
