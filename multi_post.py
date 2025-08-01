import os
import argparse
import json
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import time

def parse_arguments():
    parser = argparse.ArgumentParser(description='特定のテキストを複数のSlackチャンネルに同時投稿します')
    parser.add_argument('--message', type=str, required=True, help='投稿するメッセージ')
    parser.add_argument('--channels', type=str, nargs='+', required=True, help='投稿先チャンネルID（複数指定可能）')
    parser.add_argument('--dry-run', action='store_true', help='実際に投稿せず、プレビューのみ表示')
    parser.add_argument('--delay', type=float, default=1.0, help='チャンネル間の投稿間隔（秒）')
    parser.add_argument('--thread-ts', type=str, help='スレッドのタイムスタンプ（スレッドに返信する場合）')
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

def get_channel_info(client, channel_id):
    """チャンネル情報を取得"""
    try:
        response = client.conversations_info(channel=channel_id)
        if response["ok"]:
            return response["channel"]
    except SlackApiError as e:
        print(f"チャンネル情報取得エラー ({channel_id}): {e}")
    return None

def validate_channels(client, channel_ids):
    """チャンネルIDの妥当性を確認"""
    valid_channels = []
    invalid_channels = []
    
    for channel_id in channel_ids:
        channel_info = get_channel_info(client, channel_id)
        if channel_info:
            valid_channels.append({
                'id': channel_id,
                'name': channel_info['name'],
                'is_member': channel_info.get('is_member', False)
            })
        else:
            invalid_channels.append(channel_id)
    
    return valid_channels, invalid_channels

def post_message(client, channel_id, message, thread_ts=None):
    """メッセージを投稿"""
    try:
        response = client.chat_postMessage(
            channel=channel_id,
            text=message,
            thread_ts=thread_ts
        )
        
        if response["ok"]:
            return {
                'success': True,
                'timestamp': response["ts"],
                'permalink': response.get("permalink")
            }
        else:
            return {
                'success': False,
                'error': response.get("error", "Unknown error")
            }
    except SlackApiError as e:
        return {
            'success': False,
            'error': str(e)
        }

def confirm_posting(message, channels):
    """投稿の確認"""
    print("\n=== 投稿内容の確認 ===")
    print(f"メッセージ: {message}")
    print(f"投稿先チャンネル数: {len(channels)}")
    print("\n投稿先:")
    for channel in channels:
        member_status = "✓ メンバー" if channel['is_member'] else "⚠️ 非メンバー"
        print(f"  #{channel['name']} ({channel['id']}) - {member_status}")
    
    print("\nこの内容で投稿しますか？ (y/N): ", end="")
    response = input().strip().lower()
    return response in ['y', 'yes']

def main():
    args = parse_arguments()
    
    # Slackトークンを取得
    token = get_slack_token()
    if not token:
        return
    
    # Slack APIクライアントを初期化
    client = WebClient(token=token)
    
    # チャンネルの妥当性を確認
    print("チャンネル情報を確認中...")
    valid_channels, invalid_channels = validate_channels(client, args.channels)
    
    if invalid_channels:
        print(f"\n⚠️ 無効なチャンネルID: {', '.join(invalid_channels)}")
        print("これらのチャンネルはスキップされます。")
    
    if not valid_channels:
        print("有効なチャンネルが見つかりませんでした。")
        return
    
    # 非メンバーのチャンネルがある場合の警告
    non_member_channels = [ch for ch in valid_channels if not ch['is_member']]
    if non_member_channels:
        print(f"\n⚠️ 以下のチャンネルのメンバーではありません:")
        for channel in non_member_channels:
            print(f"  #{channel['name']} ({channel['id']})")
        print("投稿できない可能性があります。")
    
    # ドライランの場合
    if args.dry_run:
        print("\n=== ドライラン（実際には投稿されません） ===")
        print(f"メッセージ: {args.message}")
        print(f"投稿先チャンネル数: {len(valid_channels)}")
        for channel in valid_channels:
            print(f"  #{channel['name']} ({channel['id']})")
        return
    
    # 投稿確認
    if not confirm_posting(args.message, valid_channels):
        print("投稿をキャンセルしました。")
        return
    
    # 投稿実行
    print("\n投稿を開始します...")
    results = []
    
    for i, channel in enumerate(valid_channels):
        print(f"投稿中... ({i+1}/{len(valid_channels)}) #{channel['name']}")
        
        result = post_message(
            client, 
            channel['id'], 
            args.message, 
            args.thread_ts
        )
        
        result['channel'] = channel
        results.append(result)
        
        if result['success']:
            print(f"  ✓ 投稿完了")
        else:
            print(f"  ✗ 投稿失敗: {result['error']}")
        
        # 次のチャンネルへの投稿前に待機
        if i < len(valid_channels) - 1:
            time.sleep(args.delay)
    
    # 結果サマリー
    successful_posts = [r for r in results if r['success']]
    failed_posts = [r for r in results if not r['success']]
    
    print(f"\n=== 投稿結果 ===")
    print(f"成功: {len(successful_posts)}件")
    print(f"失敗: {len(failed_posts)}件")
    
    if successful_posts:
        print(f"\n✓ 投稿成功:")
        for result in successful_posts:
            print(f"  #{result['channel']['name']}")
    
    if failed_posts:
        print(f"\n✗ 投稿失敗:")
        for result in failed_posts:
            print(f"  #{result['channel']['name']}: {result['error']}")
    
    # 出力ファイルに結果を保存
    output_path = os.path.join('/app/output', 'multi_post_results.json') if os.path.exists('/app/output') else 'multi_post_results.json'
    
    output_data = {
        'message': args.message,
        'timestamp': time.time(),
        'channels': len(valid_channels),
        'successful': len(successful_posts),
        'failed': len(failed_posts),
        'results': results
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n結果を {output_path} に保存しました")

if __name__ == "__main__":
    main()