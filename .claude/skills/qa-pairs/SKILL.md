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

### Step 1: 収集（Docker）

```bash
docker run --volume $PWD:/app slackapp qa_pairs.py collect \
  --user <ID or 表示名> --days <N> --token $SLACK_TOKEN
# → outputs/qa_pairs/<user_id>.json
```

出力 JSON:
- `qa_pairs[]` = `{role, source:"thread", channel_id, channel_name, thread_ts, permalink, question:{ts,datetime,user,text}, answers:[{ts,datetime,user,text,is_target_user}]}`
  - スレッドは期間外の返信も含めて全体を取る
  - スレッドの構造だけで集めているので、質問でないスレッド（雑談・告知など）も入る
- `standalone_posts[]` = スレッドに属さない本人の投稿 `{ts, datetime, channel_id, channel_name, text, permalink, is_thread_reply}`

### Step 2: スレッド外の投稿が「回答」かを判定する

`standalone_posts` を読み、直前の他者の発言を受けた回答・返答に見えるものを選ぶ。
- 回答とみなすもの: 説明・可否・手順の案内、「それは〜です」「確認しました」など、前の発言がないと意味が通らないもの
- 回答とみなさないもの: 新しい話題の告知・質問、定型の挨拶（出退勤・離席など）
- 迷ったものは入れる（Step 4 で質問を特定できなければ外れる）

選んだものを `outputs/qa_pairs/<user_id>_targets.json` に `[{"channel_id", "ts", "reason"}]` で書く。
一つもなければ Step 3・4 は飛ばす。

### Step 3: 直前の発言を取る（Docker）

```bash
docker run --volume $PWD:/app slackapp qa_pairs.py context \
  --targets outputs/qa_pairs/<user_id>_targets.json --limit 20 \
  --output outputs/qa_pairs/<user_id>_context.json --token $SLACK_TOKEN
```

`targets[].preceding` に、その投稿より前の発言が古い順で最大 N 件入る（本人の投稿そのものは含まない）。

### Step 4: 質問を特定する

各 target について、`preceding` の中から本人の投稿が答えている発言を選ぶ。
- 特定できたら `role: "answerer", source: "channel_context"` の組として加える（question = その発言、answers = 本人の投稿）
- 特定できなければ外す。推測で結びつけない

### Step 5: Markdown にする

`outputs/qa_pairs/<user_id>.md` を作る。
- 出力は **日本語**
- 質問・相談・依頼に当たらないスレッドは、本文を載せず末尾の「その他のスレッド」に件数とリンクだけ書く
- 発言者は `<@U...>` のまま書く（名前への変換はしない）
- 組織方針に従い、機微情報は除外・抽象化する

## 出力フォーマット（outputs/qa_pairs/<user_id>.md）

```
# 質問と回答: <@U...>（<期間>）

## 本人が答えた質問（N 組）

### <channel_name> / <質問の日時> （[リンク](<permalink>)）
**Q** <@質問者>: <質問の本文>

**A**
- <@発言者> (<日時>): <本文>（本人の発言は太字）

## 本人の質問と回答（N 組）
（同じ形）

## その他のスレッド（N 件）
- <channel_name> [リンク](<permalink>)
```
