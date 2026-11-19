---
name: auto-draft-reply
description: 指定チャンネルで自分宛てのメンションのうち未回答のものを拾い、qa-pairs の過去の Q&A を根拠に回答案を作る。承認した本文を出すだけで、投稿はしない
argument-hint: "--channel <ID> --knowledge <qa_pairs.md> [--notes <修正メモ.md>] [--days N]"
---

自分宛てのメンションのうち、メンションより後に本人の返信もリアクションもないものに回答案を作る。
**投稿はしない**。本人が承認した本文とスレッドのリンクを出し、本人が Slack に貼る
（トークンに chat:write がなく、投稿の最後の一手も人に残すため）。

引数:
- `--channel <ID>`（必須）
- `--knowledge <path>`（必須）: qa-pairs が作った qa_pairs.md
- `--notes <path>`（任意）: 承認時に直した点を書き溜める Markdown。
  省略時は `.claude/skills/auto-draft-reply/notes/<channel_id>.md`。ファイルがなければ作る
  （次回以降も Step 3 で読むため、同じチャンネルでは同じファイルを使い続ける）
- `--days N`（任意、既定 7）

引数が足りなければユーザーに尋ねる。自分のユーザー ID は環境変数 `SLACK_USER_ID` を使う。

## 組織方針（厳守）

- 回答案に、社員のメールアドレスや顧客の個人情報を載せない。knowledge にあっても写さない
- ツールの利用可否やアカウント発行などの判断は決裁に当たる。過去に同じ判断があっても、承認で本人が決める

## 手順

### Step 1: 未回答のメンションを拾う（Docker）

```bash
docker run --volume $PWD:/app slackapp unanswered_mentions.py --token $SLACK_TOKEN \
  --mentioned-user $SLACK_USER_ID --channel <ID> --days <N> \
  --output outputs/draft_replies/unanswered_$(date +%Y%m%d-%H%M%S).json
```

出力の各件: `timestamp`（メンションの ts）、`thread_ts`（スレッド外なら null）、`author.id`、`text`。
0 件ならそう伝えて終わる。

### Step 2: スレッドを読み、返答不要なものを外す

1 件ずつスレッド全体を取る（`?thread_ts=` は thread_ts が null なら付けない）:

```bash
docker run --volume $PWD:/app --volume $PWD/.claude/skills/summarize-thread:/skills \
  -e PYTHONPATH=/app slackapp /skills/fetch_thread.py \
  "https://slack.com/archives/<channel>/p<timestamp の点を除いたもの>?thread_ts=<thread_ts>" \
  --token $SLACK_TOKEN
```

次のものは回答案を作らず「返答不要」として外す（迷ったら回答案を作る）:
- お礼・了承だけの投稿
- 本人は cc だけで、宛先の人が既に返信している
- 本人に問いかけていない意見・感想

### Step 3: 根拠を探す

- `--notes` があれば最初に全部読む。knowledge と食い違うときは notes を優先する
- 質問からツール名や手続きの語を取り、`--knowledge` を Grep する（例: `LangSmith|Langfuse`）
- ヒットした行を含む `### ` の組だけを Read の offset/limit で読む（knowledge は 18 万字を超えるため全文は読まない）

### Step 4: 回答案を作る

- 口調は knowledge の本人の発言（太字の行）に合わせる
- 根拠にした組の日付とリンクを案の下に並べる（投稿する本文には入れない）。半年より前のものは「古い根拠」と書く
- 根拠がない、または可否の判断が要るのに過去の判断がないときは、推測で答えず「根拠なし（要判断）」として論点だけ書く

### Step 5: 承認

1 件ずつ AskUserQuestion で尋ねる。preview に投稿する本文の全文を入れ、question に質問の要約と根拠の日付を書く。
選択肢は次の 3 つ:
- このまま使う
- 修正する: 直したい点を選択肢のメモか Other に書いてもらう。反映した案を作り直し、同じ形でもう一度尋ねる
  （「このまま使う」か「見送る」になるまで繰り返す）
  メモが空なら推測で直さず、直したい点をテキストで尋ねて待つ
- 見送る

修正を経て使ったものは Step 6 で修正メモに残す。

### Step 6: 修正メモを書く

直して使ったときは、`--notes` に追記する（後で方針集にする素材）:

```
## <日付> <スレッドのリンク>
- 元の案: <要旨>
- 直した点: <何をどう直したかと、分かれば理由>
```

### Step 7: 結果を出す

次の形でまとめて出す。本文はコードブロックに入れ、そのままコピーできるようにする。
- 貼るもの: スレッドのリンクと本文
- 見送り・返答不要・根拠なし: リンクと理由を 1 行ずつ
