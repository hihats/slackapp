---
name: qa-pairs
description: 指定Slackユーザーの発言から、本人が答えた質問と、本人の質問への回答を集め、質問と回答のセットを Markdown にまとめる
argument-hint: "[--user <ID or 表示名>] [--days N | --after YYYY-MM-DD --before YYYY-MM-DD] [--channel <ID>]"
---

指定した Slack ユーザーの発言から、次の2種類の「質問と回答のセット」を集める。
- answerer: 本人が他者の質問に答えたもの
- asker: 本人の質問に他者が答えたもの

引数（すべて任意）:
- `--user <ID or 表示名>`: 対象ユーザー（省略時はユーザーに確認する）
- `--days N` または `--after` / `--before`: 期間（省略時は30日。併用不可）
- `--channel <ID>`: チャンネルを絞る

## 前提

- Slack API を触る処理は **Docker** で実行する。
- トークンは User Token。`search:read` と `channels:history` / `groups:history` / `im:history` / `mpim:history` が必要。
- **本人の同意を前提とする**。対象者や用途が不明なら実行前に確認する。

## 組織方針（厳守）

顧客の個人情報（氏名・メールアドレス・口座情報など）や、未公表の業績・財務情報に当たりうる内容は、
Markdown にする段階で除外または抽象化する（該当したら「(機微情報のため省略)」と書く）。

## 手順

中間ファイルは実行ごとのディレクトリ（RUN_DIR）に置かれる。パスは collect が最後に表示するものを
そのまま使い、自分で組み立てない。以下の `<targets>` などは、その表示にある役割ごとのパスを指す。

### Step 1: 収集して索引を作る（Docker）

スキルに渡された引数（`--days` または `--after`/`--before`、`--channel`）は、
**指定されたものだけをそのまま** `collect` に渡す。指定されていないものは付けない
（期間がなければスクリプトの既定 30 日になる）。collect が失敗したら、ここで止める。

```bash
docker run --volume $PWD:/app slackapp qa_pairs.py collect \
  --user <ID or 表示名> [--days <N> | --after <YYYY-MM-DD> --before <YYYY-MM-DD>] \
  [--channel <チャンネルID>] --token $SLACK_TOKEN
# → 最後に RUN_DIR と役割ごとのパス（collect, index, targets, context, judgement, markdown）を表示する

docker run --volume $PWD:/app slackapp qa_pairs.py index --run-dir <RUN_DIR>
```

例（期間とチャンネルを指定）:
```bash
docker run --volume $PWD:/app slackapp qa_pairs.py collect \
  --user hihats --after 2026-10-01 --before 2026-10-07 \
  --channel C789012 --token $SLACK_TOKEN
```

以降の判定は `<collect>`（JSON）ではなく `<index>` を読む
（JSON は 30 日分で 9,000 行を超え、構造の分だけ文脈が埋まるため）。
- `## T <channel_id>:<thread_ts> | <role> | #<channel> | <日時> | 返信 N（本人 M）`
  - 次の行から親の本文（全文）。answerer の組には `> 本人の最初の返信: <冒頭100字>` が続く
  - スレッドは期間外の返信も含めて全体を取っている
  - スレッドの構造だけで集めているので、質問でないスレッド（雑談・告知など）も入る
- `## S <channel_id>:<ts> | #<channel> | <日時> | <permalink>`
  - 次の行からスレッド外の本人の投稿

### Step 2: スレッド外の投稿が「回答」かを判定する

`<index>` の `S` 項目を読み、直前の他者の発言を受けた回答・返答に見えるものを選ぶ。
- 回答とみなすもの: 説明・可否・手順の案内、「それは〜です」「確認しました」など、前の発言がないと意味が通らないもの
- 回答とみなさないもの: 新しい話題の告知・質問、定型の挨拶（出退勤・離席など）
- 迷ったものは入れる（Step 4 で質問を特定できなければ外れる）

選んだものを `<targets>` に `[{"channel_id", "ts", "reason"}]` で書く（channel_id と ts は `S` のキー）。
一つもなければ Step 3・4 は飛ばす。

### Step 3: 直前の発言を取る（Docker）

```bash
docker run --volume $PWD:/app slackapp qa_pairs.py context \
  --run-dir <RUN_DIR> --limit 3 --token $SLACK_TOKEN
```

`<context>` の `targets[].preceding` に、その投稿より前の発言が古い順で最大 3 件入る
（本人の投稿そのものは含まない）。
間に他の発言が挟まっているのにスレッドを使わず返信することは考えにくいため、
これより前は遡らない。

### Step 4: 質問を特定する

各 target について、`preceding` を新しいほうから見て、次の発言を飛ばした
**最初の1件だけ**を質問の候補にする。
- 本人の発言（答えを複数の投稿に分けた場合）
- bot の発言（`user` が `B` で始まるもの、`USLACKBOT`）

- 本人の投稿がその候補に答えていれば、Step 5 で書く `<judgement>` の `channel_context_pairs` に次の形で入れる
  ```
  {"role": "answerer", "source": "channel_context", "channel_name": <S のチャンネル名（# なし）>,
   "permalink": <S の permalink>,
   "question": {"datetime", "user", "text"}（候補の発言。<context> から）,
   "answers": [{"datetime": <S の日時>, "user": <user_id>, "text": <S の本文>, "is_target_user": true}]}
  ```
- 候補に答えていなければ外す。それより前の発言とは結びつけない
- 3 件すべてが飛ばす対象で候補がなければ外す

### Step 5: スレッドを判定し、Markdown にする

1. `<index>` の `T` 項目から、返答や対応を求めていないスレッドを選ぶ
   - 載せる: 質問・相談・依頼・確認のお願いなど。本文の後半や、本人の最初の返信
     （「対応しました」など）から依頼と分かるものも含む
   - 「その他」に回す: 返答を求めていない告知・共有・雑談・定型の投稿（日報など）だけ
   - 迷ったら載せる
2. `<judgement>` を書く（該当がなくても空のリストで書く）
   ```
   {"other_threads": ["<channel_id>:<thread_ts>", ...], "channel_context_pairs": [Step 4 の組]}
   ```
3. render（Docker）
   ```bash
   docker run --volume $PWD:/app slackapp qa_pairs.py render \
     --run-dir <RUN_DIR> --period "<期間>"
   ```
   - `--period`: 渡した期間とチャンネル（例 `2026-10-06、#jp_em`）。期間を渡していなければ、
     collect が表示した Search query の `after:` の翌日〜今日（`after:` はその日を含まない）
   - `other_threads` のキーが collect の結果にないと ValueError で止まる。`<index>` から写し直す
4. `<markdown>` を読み、組織方針に当たる箇所を「(機微情報のため省略)」などに Edit で置き換える
   - 30 日分で約 1,700 行・15 万字になる。Read は offset/limit で分けて読む
   - 発言者は `<@U...>` のまま書く（名前への変換はしない）
5. ユーザーに `<markdown>` のパスを伝える

## 出力フォーマット（render が書く。手で書かない）

```
# 質問と回答: <@U...>（<期間>）

## 本人が答えた質問・依頼（N 組）

### <channel_name> / <質問の日時> （[リンク](<permalink>)）
**Q** <@質問者>: <質問の本文>

**A**
- <@発言者> (<日時>): <本文>（本人の発言は太字）

## 本人の質問・依頼と回答（N 組）
（同じ形）

## その他のスレッド（N 件）
- <channel_name> [リンク](<permalink>)
```
