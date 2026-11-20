---
name: summarize-thread
description: Slack スレッドの permalink を受け取り、構造化要約（参加者/論点/決定事項/TODO/補足）を日本語で出力する
argument-hint: "<Slack thread permalink>"
---

`$ARGUMENTS` を Slack スレッドの permalink として受け取り、スレッド全体を構造化して要約してください。

- 第1引数: Slack スレッドの permalink（必須）
  - 例: `https://example.slack.com/archives/C0123456789/p1700000000123456?thread_ts=1699999999.000100`

引数が無い場合はユーザーに permalink を尋ねる。

## 手順

### Step 1: スレッド取得

Docker 上で `fetch_thread.py` を実行し、スレッド本文と参加者情報を JSON で取得する:

```bash
docker run --volume $PWD:/app --volume $PWD/.claude/skills/summarize-thread:/skills -e PYTHONPATH=/app slackapp /skills/fetch_thread.py "<permalink>" --token $SLACK_TOKEN > /tmp/thread.json
```

`PYTHONPATH=/app` は `slack_conversations` / `slack_rate_limit` を import するために必要（`/skills/` 直下から起動すると sys.path に `/app` が入らないため）。

JSON の構造:
- `permalink`, `channel_id`, `thread_ts`
- `participants`: `[{user_id, display_name}, ...]`
- `messages`: `[{ts, user_id, text}, ...]`（時系列順、親メッセージを含む）

### Step 2: 関連リンク先の参照（必要に応じて）

`/tmp/thread.json` の `messages[].text` から URL を抽出し、要約の理解に資するものを取得する。

- **Slack permalink**（`https://*.slack.com/archives/.../p...`）:
  - 起点スレッド・関連スレッドとして本スレッドの背景になっている可能性が高い。
  - 同じ `fetch_thread.py` を使って取得する（出力先は `/tmp/thread_<連番>.json` 等）。
  - ただし**再帰深度は1段まで**（取得したスレッドの中の Slack permalink はさらに掘らない）。
- **GitHub URL**（`https://github.com/<org>/<repo>/blob/<ref>/<path>` 等）:
  - `gh api repos/<org>/<repo>/contents/<path>?ref=<ref> --jq .content | base64 -d` でファイル内容を取得する。
  - 行範囲指定（`#L100-L120` など）がある場合はその範囲だけ抜き出して解釈する。
- **その他の URL**（Notion / 社内ツール / 公開ドキュメント等）:
  - 利用可能な **MCP サーバが対応サービスを持つ場合はそれを優先**（例: Notion なら Notion MCP、Linear なら Linear MCP 等）。MCP リストは実行時に判断する。
  - MCP が無い／対応していない場合は WebFetch で要約取得する（公開かつ取得可能なものに限る）。
  - アクセス権が無いものは無理に取得しない。

取得できなかったリンクはその旨を補足セクションで明示する。

### Step 3: 要約

`/tmp/thread.json`（および Step 2 で取得した関連情報）を読み込み、以下のルールで要約する:

- メッセージ本文中の `<@U...>` 形式のメンションは `participants` の `display_name` に置換する
- 発言者の表示は `display_name` を使う
- 出力は **日本語固定**

## 出力フォーマット

```
## スレッド要約

- permalink: <permalink>
- 参加者: <display_name の一覧>

### 背景（関連スレッド / 起点があれば）
- 本スレッドからは見えない経緯・派生元のサマリ
- 無ければセクションごと省略

### コード現状（関連 GitHub リンクがあれば）
- 参照されたファイル名と、本スレッドの議論に関わる実装状況の要点
- 無ければセクションごと省略

### 論点
- 箇条書きで列挙

### 決定事項
- 箇条書きで列挙（無ければ「なし」）

### TODO / アクションアイテム
- `担当: <名前>` を可能な範囲で付与（不明なら「未割当」）
- 無ければ「なし」

### 補足（未解決事項・要確認）
- 箇条書き、無ければ「なし」
- Step 2 で取得を試みて失敗したリンクがあればここに明示する
```
