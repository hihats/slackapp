"""
指定チャンネルの全投稿（スレッド返信を含む）の全文を取得し、JSON に保存する。
"""

import argparse
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from datetime import time as day_time
from decimal import Decimal
from pathlib import Path

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from slack_conversations import fetch_all_channel_history, fetch_all_thread_replies

JST = timezone(timedelta(hours=9))
# conversations.replies は Tier 3。共通関数はスレッドをまたぐ呼び出しの間では待たないためこちらで待つ
TIER3_INTERVAL = 1.5
# channel_not_found は含めない。履歴が取れた後に出るなら異常で、黙って飛ばすと取りこぼしに気づけない
SKIPPABLE_THREAD_ERRORS = {"thread_not_found"}


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description="指定チャンネルの全投稿を全文で取り出す")
    parser.add_argument("--channel", required=True, help="チャンネルID")
    parser.add_argument("--token", type=str, default=os.environ.get("SLACK_TOKEN"),
                        help="Slackトークン（既定は環境変数 SLACK_TOKEN）")
    parser.add_argument("--after", type=date.fromisoformat,
                        help="この日以降（当日を含む, YYYY-MM-DD, JST）。省略時は最初から")
    parser.add_argument("--before", type=date.fromisoformat,
                        help="この日以前（当日を含む, YYYY-MM-DD, JST）。省略時は最新まで")
    parser.add_argument("--output", default="channel_all_posts.json",
                        help="出力JSONファイル（既定: channel_all_posts.json）")
    return parser.parse_args(argv)


def _jst_midnight_epoch(day):
    return datetime.combine(day, day_time.min, JST).timestamp()


def to_epoch_range(after, before):
    """日付指定を conversations.history の oldest / latest（epoch 秒）に変換する。"""
    oldest = _jst_midnight_epoch(after) if after else None
    # latest は境界と同じ ts を含まないため、翌日 0 時を渡せば指定日の末尾まで入る。
    # oldest 側も境界を含まないが、inclusive=True は使わない。共通関数に引数がなく、
    # 使うと latest 側で翌日 0 時ちょうどの投稿を拾ってしまう
    latest = _jst_midnight_epoch(before + timedelta(days=1)) if before else None
    return oldest, latest


def thread_parent_ts(messages):
    return [m["ts"] for m in messages if m.get("reply_count", 0) > 0]


def fetch_thread(client, channel_id, thread_ts):
    """1 スレッドの返信を取る（親は除く）。スレッド固有のエラーなら None を返す。"""
    try:
        return fetch_all_thread_replies(client, channel_id, thread_ts)
    except SlackApiError as e:
        # リトライ上限で投げられる例外は response が None（slack_rate_limit.py）
        if (e.response or {}).get("error") not in SKIPPABLE_THREAD_ERRORS:
            raise
        return None


def fetch_all_replies(client, channel_id, parent_ts_list):
    """全スレッドの返信を順に取り、(返信, 取れなかったスレッドの ts) を返す。"""
    replies, skipped = [], []
    for i, thread_ts in enumerate(parent_ts_list):
        if i:
            time.sleep(TIER3_INTERVAL)
        fetched = fetch_thread(client, channel_id, thread_ts)
        if fetched is None:
            skipped.append(thread_ts)
            continue
        replies.extend(fetched)
    return replies, skipped


def merge_unique(messages, replies):
    """ts で重複を除き、古い順に並べる。"""
    by_ts = {m["ts"]: m for m in [*messages, *replies]}
    # float にしない。ts は 16 桁あり、float では 1 マイクロ秒差の順序が崩れうる
    return sorted(by_ts.values(), key=lambda m: Decimal(m["ts"]))


def format_post(message):
    """検査に使うキーだけを取り出す（投稿者・リアクションなどは残さない）。"""
    ts, thread_ts = message["ts"], message.get("thread_ts")
    return {
        "ts": ts,
        "datetime": datetime.fromtimestamp(float(ts), JST).strftime("%Y-%m-%d %H:%M:%S"),
        "thread_ts": thread_ts,
        # reply_count では判定しない。返信側には無く、親か単独投稿かしか区別できない
        "is_thread_reply": thread_ts is not None and thread_ts != ts,
        "subtype": message.get("subtype"),
        "text": message.get("text", ""),
        "attachments": message.get("attachments", []),
        "blocks": message.get("blocks", []),
        "files": message.get("files", []),
    }


def collect_posts(client, channel_id, oldest=None, latest=None):
    """チャンネルの投稿とスレッド返信をすべて集め、(投稿, 取れなかったスレッドの ts) を返す。"""
    messages = fetch_all_channel_history(client, channel_id, oldest=oldest, latest=latest)
    parents = thread_parent_ts(messages)
    print(f"チャンネル直下 {len(messages)} 件、スレッド {len(parents)} 本（目安 {len(parents) * TIER3_INTERVAL / 60:.0f} 分）")
    replies, skipped = fetch_all_replies(client, channel_id, parents)
    return [format_post(m) for m in merge_unique(messages, replies)], skipped


def save_results(data, output_path):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _iso(day):
    return day.isoformat() if day else None


def main():
    args = parse_arguments()
    if not args.token:
        raise SystemExit("Slackトークンが未指定です（--token または環境変数 SLACK_TOKEN）")

    client = WebClient(token=args.token)
    oldest, latest = to_epoch_range(args.after, args.before)
    posts, skipped = collect_posts(client, args.channel, oldest, latest)
    save_results({
        "channel_id": args.channel,
        "after": _iso(args.after),
        "before": _iso(args.before),
        "fetched_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(posts),
        "skipped_threads": skipped,
        "messages": posts,
    }, args.output)
    print(f"保存完了: {args.output}（{len(posts)} 件、取れなかったスレッド {len(skipped)} 本）")


if __name__ == "__main__":
    main()
