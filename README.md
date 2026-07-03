# Slack App

Slackメッセージの分析・可視化ツール群。キーワード検索、ワードクラウド生成、未回答メンション検出、リアクション分析などをDockerコンテナ上で実行する。

## セットアップ

```bash
# Docker イメージのビルド
docker build -t slackapp .

# 依存パッケージのインストール（ローカル開発用）
pip install -r requirements.txt
```

## スクリプト一覧

### ワードクラウド生成

```bash
docker run --volume $PWD:/app slackapp wordclouds.py \
  --token $SLACK_TOKEN --channel $CHANNEL_ID --keyword KEYWORD \
  --days 30 --output outputs/wordcloud.png
```

### 週次メッセージ集計

```bash
docker run --volume $PWD:/app slackapp weekly_message_count.py \
  --token $SLACK_TOKEN --channel $CHANNEL_ID --keyword "検索文言" \
  --days 30 --output outputs/weekly_count_$(date +%Y%m%d).json
```

### 月次メッセージ集計

```bash
docker run --volume $PWD:/app slackapp monthly_message_count.py \
  --token $SLACK_TOKEN --channel $CHANNEL_ID --keyword "検索文言" \
  --months 3 --output outputs/monthly_count_$(date +%Y%m%d).json
```

### 未回答メンション検出

```bash
# Search API 使用（推奨・高速）
docker run --volume $PWD:/app slackapp unanswered_mentions.py \
  --token $SLACK_TOKEN --mentioned-user $SLACK_USER_ID \
  --days 30 --output outputs/unanswered_mentions_$(date +%Y%m%d).json \
  --use-search-api

# 従来方式（チャンネルごと検索）
docker run --volume $PWD:/app slackapp unanswered_mentions.py \
  --token $SLACK_TOKEN --mentioned-user $SLACK_USER_ID \
  --days 30 --output outputs/unanswered_mentions_$(date +%Y%m%d).json

# 特定チャンネルのみ
docker run --volume $PWD:/app slackapp unanswered_mentions.py \
  --token $SLACK_TOKEN --mentioned-user $SLACK_USER_ID \
  --channel $CHANNEL_ID --days 7 \
  --output outputs/unanswered_mentions_$(date +%Y%m%d).json --use-search-api
```

### チャンネル日次投稿取得

```bash
docker run --volume $PWD:/app -e SLACK_TOKEN=$SLACK_TOKEN slackapp channel_daily_posts.py \
  --channel $CHANNEL_ID --date 2026-03-25 \
  --output outputs/channel_daily_posts_$(date +%Y%m%d).json
```

### リアクション付き投稿の取得

```bash
docker run --volume $PWD:/app slackapp posts_with_my_reactions.py \
  --token $SLACK_TOKEN --days $NUMDAYS \
  --output outputs/posts_with_my_reactions_$(date +%Y%m%d).json
```

### リアクションレポート生成

```bash
# 特定ユーザーの投稿に対するリアクションレポート（全チャンネル、過去30日）
docker run --volume $PWD:/app slackapp reactions_report.py \
  --token $SLACK_TOKEN --user $SLACK_USER_ID --days 30 \
  --output outputs/reactions_report_$(date +%Y%m%d).json

# 特定チャンネルに絞り込み
docker run --volume $PWD:/app slackapp reactions_report.py \
  --token $SLACK_TOKEN --user $SLACK_USER_ID --channel $CHANNEL_ID --days 7 \
  --output outputs/reactions_report_$(date +%Y%m%d).json
```

### メッセージのリアクション取得

```bash
docker run --volume $PWD:/app slackapp message_reactions.py \
  --token $SLACK_TOKEN --channel $CHANNEL_ID --message $MESSAGE_TIMESTAMP \
  --include-user-details --output outputs/reactions_to_$MESSAGE_TIMESTAMP.json
```

### 全チャンネル取得

```bash
docker run --volume $PWD:/app slackapp get_all_channels.py \
  --token $SLACK_TOKEN --user $SLACK_USER_ID \
  --output outputs/all_channels.json
```

### 非アクティブチャンネル検出

```bash
docker run --volume $PWD:/app slackapp inactive_channels.py \
  --token $SLACK_TOKEN --channels-json outputs/all_channels.json \
  --output outputs/inactive_channels_$(date +%Y%m%d).json
```

### 日次業務まとめ（daily-report スキル）

その日の業務を、当日自分が投稿した Slack のやりとりと Claude のセッション履歴
（Claude Code + Cowork）から横断的に整理し、Markdown の業務まとめを生成する。
Claude Code のスキル `/daily-report` として実行する。

**実行環境の切り分け** — Slack API を触る処理は Docker、ローカルの Claude 履歴の
読み取りはホストで行う。Claude Code 履歴（`~/.claude/projects`）と Cowork 履歴
（`~/Library/Application Support/Claude/local-agent-mode-sessions`）はホスト固有の
パスにあるため、収集をソース別に分けている。

収集スクリプト `collect_daily.py` は `--source` で対象を切り替える:

```bash
# Slack 分（Docker・当日自分が投稿したチャンネル/DM）
docker run --volume $PWD:/app slackapp collect_daily.py \
  --source slack --date 2026-07-01 --token $SLACK_TOKEN
# → outputs/daily/2026-07-01.slack.json

# Claude 履歴分（ホスト・当日のセッション）
python collect_daily.py --source claude --date 2026-07-01
# → outputs/daily/2026-07-01.claude.json
```

生成された中間 JSON をもとに要約し、`outputs/daily/<date>.md` に保存する。
`--post-channel` を指定すると、確認のうえ凝縮サマリを指定 Slack チャンネルへ投稿する。
なお、まとめ・投稿には顧客の個人情報や未公表情報を含めない運用とする。

## コマンドライン引数

| 引数 | 説明 | 対象スクリプト |
|------|------|----------------|
| `--token` | Slack API トークン | 多数（channel_daily_posts は環境変数から取得） |
| `--channel` | チャンネルID or チャンネル名 | wordclouds, message_reactions, weekly/monthly_message_count, channel_daily_posts |
| `--user` | Slack ユーザーID | get_all_channels |
| `--mentioned-user` | メンション先ユーザーID | unanswered_mentions |
| `--channels-json` | all_channels.json のパス | inactive_channels |
| `--keyword` | 検索キーワード | wordclouds, weekly/monthly_message_count |
| `--date` | 取得日付（YYYY-MM-DD） | channel_daily_posts, collect_daily |
| `--source` | 収集対象 all/slack/claude（デフォルト: all） | collect_daily |
| `--days` | 遡る日数（デフォルト: 30） | 多数 |
| `--months` | 遡る月数（デフォルト: 3） | monthly_message_count |
| `--output` | 出力ファイルパス | 全スクリプト |
| `--format` | 出力形式 json/csv（デフォルト: json） | channel_daily_posts |
| `--use-search-api` | Search API で高速検索 | unanswered_mentions |
| `--limit` | 処理チャンネル数上限 | テスト用 |
| `--stopwords` | ストップワードファイル | wordclouds |
| `--min_freq` | 最小出現回数（デフォルト: 2） | wordclouds |
| `--positive_boost` | ポジティブワード倍率（デフォルト: 1.5） | wordclouds |

## アーキテクチャ

### 主要コンポーネント

| ファイル | 役割 |
|----------|------|
| `slack_search.py` | search.messages API の共通モジュール（ページネーション・レート制限） |
| `wordclouds.py` | ワードクラウド生成 |
| `weekly_message_count.py` | 週次メッセージ集計 |
| `monthly_message_count.py` | 月次メッセージ集計 |
| `unanswered_mentions.py` | 未回答メンション検出 |
| `channel_daily_posts.py` | チャンネル日次投稿取得 |
| `posts_with_my_reactions.py` | 自分のリアクション付き投稿取得 |
| `reactions_report.py` | ユーザー投稿へのリアクションレポート生成 |
| `message_reactions.py` | メッセージのリアクション取得 |
| `get_all_channels.py` | 全チャンネル一覧取得 |
| `inactive_channels.py` | 非アクティブチャンネル検出 |
| `collect_daily.py` | 日次業務まとめの収集（Slack + Claude Code/Cowork 履歴） |

### Docker 環境

- Python 3.11 slim ベースイメージ
- MeCab 形態素解析器 + NEologd 辞書
- 日本語フォント（Noto CJK）
- `/app/outputs/` にボリュームマウントで出力

### 設定ファイル

- `requirements.txt` — Python 依存パッケージ
- `Dockerfile` — コンテナ設定
- `stopwords.txt` — 日本語ストップワード
- `dict.csv` — MeCab カスタム辞書

## テスト

```bash
# 全テスト実行
python -m pytest tests/ -v

# slack_search モジュールのテストのみ
python -m pytest tests/test_slack_search.py -v
```

## Search API について

`--use-search-api` オプションは Slack の `search.messages` API を使用した高速検索を有効にする。

**要件:**
- ユーザートークン（Botトークン不可）+ `search:read` スコープ

**従来方式との比較:**

| | Search API | 従来方式 |
|---|---|---|
| 速度 | 1-3分 | 10-60分 |
| 準備 | 不要 | all_channels.json が必要 |
| スケーラビリティ | チャンネル数に依存しない | チャンネル数に比例 |

## Slack API レート制限

Slack Web API にはメソッドごとにレート制限がある。新しいスクリプトを作成する場合は以下を参考に適切な待機時間を設定すること。

| Tier | リクエスト/分 | 推奨間隔 |
|------|-------------|----------|
| Tier 1 | 1+ | 60秒 |
| Tier 2 | 20+ | 3秒 |
| Tier 3 | 50+ | 1.5秒 |
| Tier 4 | 100+ | 1秒 |

主なメソッドの Tier:

| メソッド | Tier | 備考 |
|----------|------|------|
| `reactions.list` | 特殊 | 2025年〜: 1リクエスト/分（非Marketplaceアプリ） |
| `conversations.history` / `conversations.replies` | Tier 3 | |
| `search.messages` | Tier 3 | |
| `users.info` | Tier 4 | |

レート制限に引っかかった場合は `Retry-After` ヘッダの値に従って待機する。共通モジュール `slack_search.py` の `handle_rate_limit()` でこの処理を自動化している。
