import os
import argparse
import json
import time
from datetime import datetime, timedelta
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
        description='最終投稿が365日以上前のチャンネルを抽出します。',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--token', type=str, required=True, help='Slack APIトークン')
    parser.add_argument('--channels-json', type=str, required=True, help='all_channels.jsonファイルのパス')
    parser.add_argument('--output', type=str, default='inactive_channels.json', help='出力ファイル名（デフォルト: inactive_channels.json）')
    parser.add_argument('--limit', type=int, help='処理するチャンネル数の上限（テスト用）')
    return parser.parse_args()

def load_channels_from_json(json_file_path):
    """all_channels.jsonからチャンネルリストを読み込み"""
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            channel_data = json.load(f)
        
        all_channels = channel_data.get("channels", [])
        print(f"JSONファイルから {len(all_channels)} 個のチャンネルを読み込みました")
        
        # パブリック・プライベートチャンネルのみフィルタリング（DM/グループDM除外）
        filtered_channels = []
        for channel in all_channels:
            if channel.get("is_channel") or channel.get("is_group"):
                if not channel.get("is_im") and not channel.get("is_mpim"):
                    filtered_channels.append(channel)
        
        print(f"パブリック・プライベートチャンネル: {len(filtered_channels)} 個")
        return filtered_channels
    
    except FileNotFoundError:
        print(f"エラー: {json_file_path} が見つかりません")
        print("先に get_all_channels.py を実行してチャンネルリストを作成してください")
        return []
    except json.JSONDecodeError as e:
        print(f"JSONファイル読み込みエラー: {e}")
        return []

def get_channel_last_message_time(client, channel_id):
    """チャンネルの最新メッセージの投稿時刻を取得"""
    try:
        response = handle_rate_limit(
            client.conversations_history,
            channel=channel_id,
            limit=1,
            include_all_metadata=False
        )
        
        if not response or not response["ok"]:
            return None
        
        messages = response.get("messages", [])
        if not messages:
            return None
        
        # 最新メッセージのタイムスタンプを取得
        latest_message = messages[0]
        timestamp = float(latest_message["ts"])
        return datetime.fromtimestamp(timestamp)
    
    except SlackApiError as e:
        if e.response["error"] == "channel_not_found":
            print(f"    チャンネル {channel_id} が見つかりません（削除済みの可能性）")
            return None
        elif e.response["error"] == "not_in_channel":
            print(f"    チャンネル {channel_id} にアクセス権限がありません")
            return None
        else:
            print(f"    チャンネル {channel_id} のメッセージ取得エラー: {e}")
            return None

def check_inactive_channels(client, channels):
    """365日以上非アクティブなチャンネルをチェック"""
    cutoff_date = datetime.now() - timedelta(days=365)
    print(f"基準日: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')} より古いチャンネルを検索中...")
    
    inactive_channels = []
    total_channels = len(channels)
    
    for i, channel in enumerate(channels):
        channel_id = channel["id"]
        channel_name = channel.get("name", channel_id)
        
        print(f"[{i+1}/{total_channels}] #{channel_name} ({channel_id}) をチェック中...")
        
        last_message_time = get_channel_last_message_time(client, channel_id)
        
        if last_message_time is None:
            print(f"    メッセージが取得できませんでした（スキップ）")
            continue
        
        print(f"    最終投稿: {last_message_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        if last_message_time < cutoff_date:
            days_since_last_post = (datetime.now() - last_message_time).days
            
            inactive_channel_info = {
                "id": channel_id,
                "name": channel_name,
                "last_message_time": last_message_time.strftime('%Y-%m-%d %H:%M:%S'),
                "days_since_last_post": days_since_last_post,
                "is_private": channel.get("is_private", False),
                "num_members": channel.get("num_members", 0),
                "created": channel.get("created", 0),
                "topic": channel.get("topic", ""),
                "purpose": channel.get("purpose", "")
            }
            
            inactive_channels.append(inactive_channel_info)
            print(f"    ✓ 非アクティブ（{days_since_last_post} 日前）")
        else:
            print(f"    アクティブ（{(datetime.now() - last_message_time).days} 日前）")
        
        # APIレート制限対策
        time.sleep(5)
    
    return inactive_channels

def save_results_to_json(inactive_channels, filename):
    """結果をJSONファイルに保存"""
    output_data = {
        "analysis_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "threshold_days": 365,
        "total_inactive_channels": len(inactive_channels),
        "inactive_channels": inactive_channels
    }
    
    # ソート（最終投稿が古い順）
    output_data["inactive_channels"].sort(key=lambda x: x["days_since_last_post"], reverse=True)
    
    # 出力パスを決定
    output_path = os.path.join('/app/output', filename) if os.path.exists('/app/output') else filename
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    return output_path

def main():
    script_start_time = time.time()
    
    args = parse_arguments()
    print(f"設定: {args}")
    
    # Slack APIクライアントを初期化
    client = WebClient(token=args.token)
    
    # チャンネルリストを読み込み
    channels = load_channels_from_json(args.channels_json)
    if not channels:
        return
    
    # チャンネル数を制限（テスト用）
    if args.limit:
        channels = channels[:args.limit]
        print(f"チャンネル数を {args.limit} 件に制限しました")
    
    print(f"対象チャンネル数: {len(channels)}")
    
    # 非アクティブなチャンネルをチェック
    inactive_channels = check_inactive_channels(client, channels)
    
    if inactive_channels:
        # 結果を保存
        output_path = save_results_to_json(inactive_channels, args.output)
        
        print(f"\n=== 分析結果 ===")
        print(f"対象チャンネル数: {len(channels)}")
        print(f"非アクティブチャンネル数: {len(inactive_channels)}")
        print(f"非アクティブ率: {len(inactive_channels) / len(channels) * 100:.1f}%")
        print(f"結果を {output_path} に保存しました")
        
        print(f"\n=== 最も古いチャンネル (上位10) ===")
        for i, channel in enumerate(inactive_channels[:10]):
            months_ago = round(channel['days_since_last_post'] / 30.0, 1)
            print(f"{i+1:2d}. #{channel['name']} ({months_ago} ヶ月前)")
            print(f"     最終投稿: {channel['last_message_time']}")
            print(f"     メンバー数: {channel['num_members']}")
            print()
        
    else:
        print(f"\n365日以上非アクティブなチャンネルは見つかりませんでした")
    
    # 実行時間を表示
    total_time = time.time() - script_start_time
    print(f"\n=== 実行完了 ===")
    print(f"総実行時間: {total_time/60:.1f}分 ({total_time:.2f}秒)")

if __name__ == "__main__":
    main()