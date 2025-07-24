import os
import argparse
import json
import csv
from datetime import datetime, timedelta
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import time
import random

def parse_arguments():
    parser = argparse.ArgumentParser(
        description='私がリアクションをつけたSlackの投稿を全て取得します\n'
                   '注意：Slack APIのレート制限により処理に時間がかかります。\n'
                   '大量のリアクションがある場合は数時間かかることがあります。',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--token', type=str, required=True, help='Slack APIトークン')
    parser.add_argument('--channel', type=str, help='特定のチャンネルID（指定しない場合は全チャンネル）')
    parser.add_argument('--days', type=int, default=30, help='遡って検索する日数（デフォルト: 30日）')
    parser.add_argument('--output', type=str, default='posts_with_my_reactions.json', help='出力ファイル名（デフォルト: posts_with_my_reactions.json）')
    parser.add_argument('--format', type=str, choices=['json', 'csv'], default='json', help='出力形式（json または csv）')
    parser.add_argument('--reaction-type', type=str, help='特定のリアクションタイプのみを取得（例: thumbsup）')
    return parser.parse_args()

def get_user_id(client):
    """自分のユーザーIDを取得"""
    try:
        response = client.auth_test()
        print(response)
        return response["user_id"]
    except SlackApiError as e:
        print(f"ユーザーID取得エラー: {e}")
        return None

# https://api.slack.com/methods/reactions.list
def get_my_reactions_list(client, user_id, oldest_timestamp, reaction_type=None):
    """自分がつけたリアクションのリストを取得"""
    reactions = []
    try:
        cursor = None
        while True:
            print(f"cursor: {cursor}")
            
            # cursorベースのページネーション（正しいパラメータ名を使用）
            params = {
                "user": user_id,
                "limit": 200  # countではなくlimitを使用、推奨値の200
            }
            if cursor:
                params["cursor"] = cursor
                
            response = client.reactions_list(**params)
            
            # HTTP 429 Too Many Requestsの場合
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 30))
                time.sleep(retry_after)
                continue
            
            if not response or not response["ok"]:
                break
            
            items = response.get("items", [])
            if not items:
                break
            
            past_threshold = 0
            for item in items:
                if past_threshold > 4:
                    return reactions
                if item["type"] == "message":
                    message_ts = float(item["message"]["ts"])
                    # タイムスタンプをYYYY-MM-DD形式に変換
                    message_date = datetime.fromtimestamp(message_ts).strftime("%Y-%m-%d")
                    if message_ts < oldest_timestamp:
                        print(f"メッセージ日付: {message_date}")
                        past_threshold += 1
                        continue
                    # 特定のリアクションタイプでフィルタリング
                    if reaction_type is None or item["reaction"] == reaction_type:
                        past_threshold = 0
                        reactions.append(item)
            
            # 次のページがあるかチェック (cursorベース)
            response_metadata = response.get("response_metadata", {})
            next_cursor = response_metadata.get("next_cursor")
            
            if not next_cursor:
                break
            
            cursor = next_cursor
            time.sleep(3)  # APIレート制限対策 Tier2 の場合は 3秒待つ
            
    except SlackApiError as e:
        print(f"リアクション履歴取得エラー: {e}")
    
    return reactions

def format_reaction_based_post_data(channel_id, message_data, user_id):
    """reactions.listから取得したデータを直接使用してフォーマット（channel_idのみ使用）"""
    # message内のreactionsから自分のリアクションを抽出
    my_reactions = []
    if "reactions" in message_data:
        for reaction in message_data["reactions"]:
            if user_id in reaction["users"]:
                my_reactions.append(reaction["name"])
    
    return {
        "channel_id": channel_id,
        "channel_name": channel_id,  # channel_idをそのまま使用
        "timestamp": message_data["ts"],
        "datetime": datetime.fromtimestamp(float(message_data["ts"])).strftime("%Y-%m-%d %H:%M:%S"),
        "text": message_data.get("text", ""),
        "user_name": message_data.get("username", ""),
        "my_reactions": my_reactions,
        "permalink": f"https://slack.com/app_redirect?channel={channel_id}&message_ts={message_data['ts']}"
    }

def save_to_json(data, filename):
    """JSONファイルに保存"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_to_csv(data, filename):
    """CSVファイルに保存"""
    if not data:
        return
    
    # my_reactions を文字列に変換
    csv_data = []
    for item in data:
        csv_item = item.copy()
        csv_item['my_reactions'] = json.dumps(item['my_reactions'], ensure_ascii=False)
        csv_data.append(csv_item)
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=csv_data[0].keys())
        writer.writeheader()
        writer.writerows(csv_data)

def main():
    args = parse_arguments()
    print(args)
    
    # Slack APIクライアントを初期化
    client = WebClient(token=args.token)
    print(client)
    # 自分のユーザーIDを取得
    user_id = get_user_id(client)
    if not user_id:
        print("ユーザーIDが取得できませんでした")
        return
    
    print(f"ユーザーID: {user_id}")
    
    # 検索期間を設定
    oldest_time = datetime.now() - timedelta(days=args.days)
    oldest_timestamp = oldest_time.timestamp()
    
    print(f"検索期間: {oldest_time.strftime('%Y-%m-%d %H:%M:%S')} から現在まで")
    
    # 自分がつけたリアクションのリストを取得
    print("自分がつけたリアクションを取得中...")
    my_reactions = get_my_reactions_list(client, user_id, oldest_timestamp, args.reaction_type)
    
    if not my_reactions:
        print("指定期間内でリアクションをつけた投稿が見つかりませんでした")
        return
    
    print(f"{len(my_reactions)}件のリアクションが見つかりました")
    # 投稿の詳細情報を取得
    posts_data = []
    
    print(f"\n投稿情報を処理中（reactions.listから直接取得）...")
    start_time = time.time()
    
    for i, reaction_item in enumerate(my_reactions):
        if i % 10 == 0:  # 10件ごとに進捗を表示
            elapsed = time.time() - start_time
            if i > 0:
                estimated_total = (elapsed / i) * len(my_reactions)
                remaining = estimated_total - elapsed
                print(f"進捗: {i}/{len(my_reactions)} ({i/len(my_reactions)*100:.1f}%) - 残り約{remaining/60:.1f}分")
        
        # チャンネルIDを取得
        channel_id = reaction_item["channel"]
                
        # 特定のチャンネルが指定されている場合のフィルタリング
        if args.channel and channel_id != args.channel:
            continue
        
        # reactions.listから直接メッセージ情報を取得
        message_data = reaction_item["message"]
        
        # 投稿データをフォーマット
        post_data = format_reaction_based_post_data(
            channel_id, 
            message_data,
            user_id
        )
        
        posts_data.append(post_data)
        
        
    # 重複を除去（同じ投稿に複数のリアクションをつけている場合）
    unique_posts = {}
    for post in posts_data:
        key = f"{post['channel_id']}_{post['timestamp']}"
        if key not in unique_posts:
            unique_posts[key] = post
        else:
            # 既存の投稿に新しいリアクションをマージ
            existing_reactions = set(unique_posts[key]['my_reactions'])
            new_reactions = set(post['my_reactions'])
            unique_posts[key]['my_reactions'] = list(existing_reactions | new_reactions)
    
    final_posts = list(unique_posts.values())
    
    # 結果を保存
    if final_posts:
        output_path = os.path.join('/app/output', args.output) if os.path.exists('/app/output') else args.output
        
        # タイムスタンプでソート（新しい順）
        final_posts.sort(key=lambda x: float(x['timestamp']), reverse=True)
        
        if args.format == 'json':
            save_to_json(final_posts, output_path)
        else:
            save_to_csv(final_posts, output_path)
        
        print(f"結果を {output_path} に保存しました")
        
        # 統計情報を表示
        print(f"\n=== 取得結果 ===")
        print(f"リアクションをつけた投稿数: {len(final_posts)}")
        
        # チャンネル別の統計
        from collections import Counter
        channel_stats = Counter([post["channel_id"] for post in final_posts])  # channel_nameではなくchannel_idを使用
        print(f"\n=== チャンネル別投稿数 ===")
        for channel, count in channel_stats.most_common(10):
            print(f"{channel}: {count}件")
        
        # リアクション別の統計
        all_my_reactions = []
        for post in final_posts:
            all_my_reactions.extend(post['my_reactions'])
        
        reaction_stats = Counter(all_my_reactions)
        print(f"\n=== リアクション別統計 ===")
        for reaction, count in reaction_stats.most_common(10):
            print(f":{reaction}: {count}回")
        
        # 最近の投稿を表示
        print(f"\n=== 最近リアクションをつけた投稿 (上位5件) ===")
        for post in final_posts[:5]:
            print(f"[{post['datetime']}] {post['channel_id']}")  # channel_nameではなくchannel_idを表示
            print(f"  投稿者: {post['user_name']}")
            print(f"  リアクション: {', '.join([':' + r + ':' for r in post['my_reactions']])}")
            print(f"  テキスト: {post['text'][:100]}{'...' if len(post['text']) > 100 else ''}")
            print(f"  リンク: {post['permalink']}")
            print()
    else:
        print("データが見つかりませんでした")

if __name__ == "__main__":
    main()