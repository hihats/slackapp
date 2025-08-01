import os
import re
import argparse
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import pandas as pd
import matplotlib.pyplot as plt
from wordcloud import WordCloud
import MeCab
from collections import Counter
import datetime
import numpy as np
from PIL import Image
import time
from positive_words import POSITIVE_WORDS

def parse_arguments():
    parser = argparse.ArgumentParser(description='Slack チャンネルからキーワード検索してワードクラウドを生成します')
    parser.add_argument('--token', type=str, required=True, help='Slack APIトークン')
    parser.add_argument('--channel', type=str, required=True, help='検索対象のチャンネルID')
    parser.add_argument('--keyword', type=str, required=True, help='検索キーワード')
    parser.add_argument('--days', type=int, default=30, help='遡って検索する日数（デフォルト: 30日）')
    parser.add_argument('--output', type=str, default='wordcloud.png', help='出力ファイル名（デフォルト: wordcloud.png）')
    parser.add_argument('--stopwords', type=str, help='ストップワードファイルのパス（オプション）')
    parser.add_argument('--min_freq', type=int, default=2, help='ワードクラウドに含める最小出現回数（デフォルト: 2）')
    parser.add_argument('--positive_boost', type=float, default=1.5, help='ポジティブワードの重み付け倍率（デフォルト: 1.5）')
    return parser.parse_args()

def get_messages(client, channel_id, keyword, days_ago):
    """指定したチャンネルから特定のキーワードを含むメッセージを取得"""
    all_messages = []
    
    # 検索対象の期間を設定
    oldest_time = (datetime.datetime.now() - datetime.timedelta(days=days_ago)).timestamp()
    
    try:
        # ページネーション処理を追加
        page = 1
        has_more = True
        
        while has_more:
            # キーワード検索を実行
            result = client.search_messages(
                query=keyword,
                count=100,  # 1リクエストでの最大値
                page=page,
                sort="timestamp",
                sort_dir="desc",
            )
            
            if not result["ok"]:
                print(f"エラー: {result['error']}")
                break
                
            matches = result["messages"]["matches"]
            if not matches:
                break
                
            # 指定チャンネルのメッセージかつ期間内のものだけを抽出
            for match in matches:
                if match["channel"]["id"] == channel_id and float(match["ts"]) >= oldest_time:
                    if match['text'] == '':
                        if 'blocks' in match and len(match['blocks']) > 1 and 'text' in match['blocks'][1] and 'text' in match['blocks'][1]['text']:
                            all_messages.append(match['blocks'][1]['text']['text'])
                    else:
                        all_messages.append(match['text'])
            
            # 次のページがあるか確認
            pagination = result["messages"]["pagination"]
            if pagination["page"] < pagination["page_count"]:
                page += 1
                # APIレート制限に配慮して少し待機
                time.sleep(1)
            else:
                has_more = False
        
        print(f"{len(all_messages)}件のメッセージが見つかりました")
        return all_messages
    
    except SlackApiError as e:
        print(f"エラー: {e}")
        return []

def tokenize_japanese(text, stopwords_list=None, keyword=None):
    """日本語テキストを形態素解析して単語リストに変換"""
    original_text = text
    
    try:
        # mecabrc ファイルのパスを指定して初期化する
        # ユーザー辞書を指定
        user_dic_option = ""
        if os.path.exists('/app/user.dic'):
            user_dic_option = "-u /app/user.dic"
            print("ユーザー辞書を使用します: /app/user.dic")
            
        if os.path.exists('/usr/local/etc/mecabrc'):
            mecab = MeCab.Tagger(f"-r /usr/local/etc/mecabrc {user_dic_option}")
        elif os.path.exists('/etc/mecabrc'):
            mecab = MeCab.Tagger(f"-r /etc/mecabrc {user_dic_option}")
        else:
            mecab = MeCab.Tagger(user_dic_option)
    except Exception as e:
        print(f"MeCab初期化エラー: {e}")
        mecab = MeCab.Tagger("")
    
    # 不要な文字やSlackの特殊形式を削除
    text = re.sub(r'<[^>]*>', '', text)  # Slackのリンクやメンション
    text = re.sub(r':[a-zA-Z0-9_+-]+:', '', text)  # 絵文字
    text = re.sub(r'https?://\S+', '', text)  # URL
    text = re.sub(r'\d+', '', text)  # 数字
    text = re.sub(r'[^\w\s]', '', text)  # 句読点
    
    parsed = mecab.parse(text)
    
    # 一旦全ての単語と品詞情報を配列に格納
    tokens = []
    for line in parsed.split('\n'):
        if line == 'EOS' or line == '':
            continue
        
        # デフォルト形式のパース
        parts = line.split('\t')
        if len(parts) >= 2:
            word = parts[0]  # 表層形
            features = parts[1].split(',')
            
            if len(features) >= 7:  # 原形情報まであるか確認
                pos = features[0]  # 品詞
                pos_detail = features[1] if len(features) > 1 else ""  # 品詞細分類1
                
                # 原形を取得 (Mecabの出力では通常7番目の要素)
                base_form = features[6]
                if base_form == '*':  # 原形が不明の場合は表層形を使用
                    base_form = word
                
                # 活用形と活用型を取得
                conjugation_type = features[4] if len(features) > 4 else "*"
                conjugation_form = features[5] if len(features) > 5 else "*"
                
                tokens.append({
                    'word': word,
                    'pos': pos,
                    'pos_detail': pos_detail,
                    'base_form': base_form,
                    'conjugation_type': conjugation_type,
                    'conjugation_form': conjugation_form
                })
    
    # トークンから単語を抽出・フィルタリング
    return extract_words_from_tokens(tokens, stopwords_list)

def extract_words_from_tokens(tokens, stopwords_list=None):
    """トークンから条件に合う単語を抽出してフィルタリング"""
    words = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        
        # 活用形の補完（例：「わかっ」→「わかった」、「おもしろかっ」→「おもしろかった」）
        if (token['pos'] == '動詞' or token['pos'] == '形容詞') and token['conjugation_form'] == '連用タ接続':
            # 次のトークンが「た」などの助動詞かチェック
            if i + 1 < len(tokens) and tokens[i+1]['pos'] == '助動詞' and tokens[i+1]['base_form'] == 'た':
                # 完全な活用形を生成
                complete_word = token['word'] + tokens[i+1]['word']
                
                # 条件を満たすか確認（長さ、ストップワード）
                if len(complete_word) > 2 and (stopwords_list is None or complete_word not in stopwords_list):
                    words.append(complete_word)
                i += 2  # 2つの単語を処理したので、インデックスを2つ進める
                continue
            # 次のトークンがない場合や助動詞でない場合、基本形を使用
            elif token['base_form'] != '*' and len(token['base_form']) > 2:
                if stopwords_list is None or token['base_form'] not in stopwords_list:
                    words.append(token['base_form'])
                i += 1
                continue
        
        # 形容詞の後に名詞が続く場合、結合する
        if token['pos'] == '形容詞' and i + 1 < len(tokens) and tokens[i+1]['pos'] == '名詞' and token['word'] not in ['ありがたい', '嬉しい']:
            compound_word = token['word'] + tokens[i+1]['word']
            
            # 結合した単語が条件を満たすか確認
            if len(compound_word) > 3 and (stopwords_list is None or compound_word not in stopwords_list):
                words.append(compound_word)
            i += 2  # 2つの単語を処理したので、インデックスを2つ進める
        else:
            # 通常の条件判定
            is_valid = False
            
            # 使用する単語形を決定（原則として原形を使用）
            word_to_use = token['base_form'] if token['base_form'] != '*' else token['word']
            
            if token['pos'] in ['形容詞', '動詞', '感動詞'] and token['pos_detail'] != '非自立' and len(word_to_use) > 2:
                is_valid = True
            elif token['pos'] == '名詞' and len(word_to_use) > 3:
                is_valid = True
            
            if is_valid and (stopwords_list is None or word_to_use not in stopwords_list):
                if word_to_use == 'スプリント':
                    word_to_use = '合同スプリント'
                words.append(word_to_use)
            
            i += 1  # 次の単語へ
    
    return words

def load_stopwords(file_path):
    """ストップワードをファイルから読み込み"""
    if file_path and os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f]
    # デフォルトのストップワード
    return ['です', 'ます', 'した', 'する', 'いる', 'ある', 'れる', 'られる', 'なる', 'よう', 'ない', 'せる']

def generate_wordcloud(words, output_file, min_freq=2, positive_boost=1.5):
    """ワードクラウドを生成して保存"""
    # 単語の出現頻度を計算
    word_counter = Counter(words)
    
    # ポジティブワードの重みを増加
    boosted_counter = Counter()
    for word, count in word_counter.items():
        # ポジティブワードリストに含まれる、またはポジティブワードで始まる単語をブースト
        is_positive = False
        for positive_word in POSITIVE_WORDS:
            if word == positive_word or word.startswith(positive_word):
                is_positive = True
                break
        
        if is_positive:
            # ポジティブワードの重みを増加（デフォルト1.5倍）
            boosted_count = int(count * positive_boost)
            print(f"ポジティブワード: {word} - 出現回数: {count} → {boosted_count} (x{positive_boost})")
            boosted_counter[word] = boosted_count
        else:
            boosted_counter[word] = count
    
    # 最小出現回数でフィルタリング
    filtered_words = {word: count for word, count in boosted_counter.items() if count >= min_freq}
    if not filtered_words:
        print(f"最小出現回数{min_freq}以上の単語が見つかりませんでした。設定を下げて再試行してください。")
        return False
    
    # フォントパスを検索
    font_path = None
    possible_font_paths = [
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',    # Dockerコンテナ内のNotoフォント
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
        '/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc'           # Mac OSのフォント（念のため）
    ]
    
    for path in possible_font_paths:
        if os.path.exists(path):
            font_path = path
            break
    
    if not font_path:
        print("警告: 日本語フォントが見つかりません。デフォルトフォントを使用します。")
    
    # ワードクラウド生成
    wordcloud = WordCloud(
        font_path=font_path,  # 日本語フォント（環境に合わせて変更）
        width=800,
        height=600,
        background_color='white',
        max_words=100,
        collocations=False
    ).generate_from_frequencies(filtered_words)
    
    # 画像として保存
    plt.figure(figsize=(10, 8))
    plt.imshow(wordcloud, interpolation='bilinear')
    plt.axis('off')
    plt.tight_layout()
    
    # 出力ディレクトリを確認
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    plt.savefig(output_file, dpi=300)
    plt.close()
    
    print(f"ワードクラウドを{output_file}に保存しました")
    
    # 出現頻度の多い単語を表示
    print("\n出現頻度の高い単語トップ10:")
    for word, count in boosted_counter.most_common(10):
        is_positive = any(word == pw or word.startswith(pw) for pw in POSITIVE_WORDS)
        if is_positive:
            print(f"{word}: {count}回 (ポジティブワード✨)")
        else:
            print(f"{word}: {count}回")
    
    return True

def main():
    args = parse_arguments()
    print(args)

    # Slack APIクライアントを初期化
    client = WebClient(token=args.token)
    
    # ストップワードのロード
    stopwords_list = load_stopwords(args.stopwords)
    
    # メッセージの取得
    messages = get_messages(client, args.channel, args.keyword, args.days)
    
    if not messages:
        print("メッセージが見つかりませんでした")
        return
    
    # すべてのメッセージを結合
    all_text = ' '.join(messages)
    
    # テキストの形態素解析（検索キーワードを引数として渡す）
    words = tokenize_japanese(all_text, stopwords_list, args.keyword)
    
    # ワードクラウドの生成
    output_path = os.path.join('/app/output', args.output)
    generate_wordcloud(words, output_path, args.min_freq, args.positive_boost)

if __name__ == "__main__":
    main()
