import os
import argparse
import json
import time
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

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
        description='指定したユーザーが参加しているチャンネルのリストを取得してJSONファイルに保存します。',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--token', type=str, required=True, help='Slack APIトークン')
    parser.add_argument('--user', type=str, required=True, help='対象ユーザーのID')
    parser.add_argument('--output', type=str, default='all_channels.json', help='出力ファイル名（デフォルト: all_channels.json）')
    return parser.parse_args()

def get_user_channels(client, user_id):
    """指定したユーザーが参加しているチャンネルのリストを取得"""
    channels = []
    try:
        cursor = None
        page_count = 0
        
        while True:
            page_count += 1
            print(f"ページ {page_count} を取得中...")
            
            response = handle_rate_limit(
                client.users_conversations,
                user=user_id,
                types="public_channel,private_channel,mpim,im",
                exclude_archived=True,
                limit=200,
                cursor=cursor
            )
            
            if not response or not response["ok"]:
                print(f"API応答エラー: {response}")
                break
            
            page_channels = response.get("channels", [])
            print(f"  このページで取得したチャンネル数: {len(page_channels)}")
            channels.extend(page_channels)
            
            response_metadata = response.get("response_metadata", {})
            next_cursor = response_metadata.get("next_cursor")
            
            if not next_cursor:
                break
            
            cursor = next_cursor
            time.sleep(5)  # APIレート制限対策
        
        print(f"合計 {len(channels)} 個のチャンネルが見つかりました")
        
        # priority順にソート（降順：高いpriorityが先頭）
        channels.sort(key=lambda x: x.get("priority", 0), reverse=True)
        print("チャンネルをpriority順にソートしました")
        
        return channels
    
    except SlackApiError as e:
        print(f"チャンネル取得エラー: {e}")
        return []

def save_channels_to_json(channels, filename):
    """チャンネルリストをJSONファイルに保存"""
    # 出力用のデータを整理
    channel_data = {
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_channels": len(channels),
        "channels": []
    }
    
    for channel in channels:
        channel_info = {
            "id": channel["id"],
            "name": channel.get("name", ""),
            "is_channel": channel.get("is_channel", False),
            "is_group": channel.get("is_group", False),
            "is_im": channel.get("is_im", False),
            "is_mpim": channel.get("is_mpim", False),
            "is_private": channel.get("is_private", False),
            "is_member": channel.get("is_member", False),
            "num_members": channel.get("num_members", 0),
            "created": channel.get("created", 0),
            "topic": channel.get("topic", {}).get("value", ""),
            "purpose": channel.get("purpose", {}).get("value", ""),
            "priority": channel.get("priority", 0)
        }
        channel_data["channels"].append(channel_info)
    
    # 出力パスを決定
    output_path = os.path.join('/app/output', filename) if os.path.exists('/app/output') else filename
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(channel_data, f, ensure_ascii=False, indent=2)
    
    return output_path

def main():
    script_start_time = time.time()
    
    args = parse_arguments()
    print(f"設定: {args}")
    
    # Slack APIクライアントを初期化
    client = WebClient(token=args.token)
    
    print(f"ユーザー {args.user} が参加しているチャンネルを取得中...")
    channels = get_user_channels(client, args.user)
    
    if not channels:
        print("チャンネルが見つかりませんでした")
        return
    
    # JSONファイルに保存
    output_path = save_channels_to_json(channels, args.output)
    
    print(f"\n=== 結果 ===")
    print(f"取得チャンネル数: {len(channels)}")
    print(f"結果を {output_path} に保存しました")
    
    # チャンネル種別の統計
    channel_types = {
        "public_channels": 0,
        "private_channels": 0,
        "direct_messages": 0,
        "multi_person_direct_messages": 0
    }
    
    for channel in channels:
        if channel.get("is_channel") and not channel.get("is_private"):
            channel_types["public_channels"] += 1
        elif channel.get("is_group") or (channel.get("is_channel") and channel.get("is_private")):
            channel_types["private_channels"] += 1
        elif channel.get("is_im"):
            channel_types["direct_messages"] += 1
        elif channel.get("is_mpim"):
            channel_types["multi_person_direct_messages"] += 1
    
    print(f"\n=== チャンネル種別統計 ===")
    print(f"パブリックチャンネル: {channel_types['public_channels']} 個")
    print(f"プライベートチャンネル: {channel_types['private_channels']} 個")
    print(f"ダイレクトメッセージ: {channel_types['direct_messages']} 個")
    print(f"グループDM: {channel_types['multi_person_direct_messages']} 個")
    
    # 上位10のパブリックチャンネル（メンバー数順）
    public_channels = [ch for ch in channels if ch.get("is_channel") and not ch.get("is_private")]
    public_channels.sort(key=lambda x: x.get("num_members", 0), reverse=True)
    
    print(f"\n=== パブリックチャンネル (メンバー数上位10) ===")
    for i, channel in enumerate(public_channels[:10]):
        name = channel.get("name", channel["id"])
        members = channel.get("num_members", 0)
        print(f"{i+1:2d}. #{name} ({members} メンバー)")
    
    # 実行時間を表示
    total_time = time.time() - script_start_time
    print(f"\n=== 実行完了 ===")
    print(f"総実行時間: {total_time/60:.1f}分 ({total_time:.2f}秒)")

if __name__ == "__main__":
    main()