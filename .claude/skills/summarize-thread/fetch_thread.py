"""Slack スレッドを permalink から取得し、構造化 JSON を stdout に出力する。"""

import argparse
import contextlib
import json
import re
import sys
import time
from typing import Dict, List, Tuple
from urllib.parse import urlparse, parse_qs

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from slack_conversations import fetch_all_thread_replies
from slack_rate_limit import handle_rate_limit

# users.info は Tier 4 (100+ req/min)
_TIER4_INTERVAL = 1.0


def parse_permalink(permalink: str) -> Tuple[str, str]:
    """Slack permalink を (channel_id, thread_ts) に分解する。"""
    parsed = urlparse(permalink)
    m = re.match(r"^/archives/([^/]+)/p(\d+)$", parsed.path)
    if not m:
        raise ValueError(f"Invalid Slack permalink: {permalink}")
    channel_id, ts_no_dot = m.group(1), m.group(2)

    qs = parse_qs(parsed.query)
    if "thread_ts" in qs:
        thread_ts = qs["thread_ts"][0]
    else:
        if len(ts_no_dot) < 7:
            raise ValueError(f"Invalid timestamp in permalink: {ts_no_dot}")
        thread_ts = f"{ts_no_dot[:-6]}.{ts_no_dot[-6:]}"

    return channel_id, thread_ts


def resolve_user_names(client: WebClient, user_ids: List[str]) -> Dict[str, str]:
    """user_id を一括で表示名に解決する。bot_id 等は user_id をそのまま名前にする。"""
    unique_ids, resolvable = _split_ids(user_ids)

    name_map: Dict[str, str] = {uid: uid for uid in unique_ids}
    for i, uid in enumerate(resolvable):
        if i > 0:
            time.sleep(_TIER4_INTERVAL)
        name_map[uid] = _fetch_name(client, uid)
    return name_map


def _split_ids(user_ids: List[str]) -> Tuple[List[str], List[str]]:
    unique_ids = sorted({uid for uid in user_ids if uid})
    resolvable = [uid for uid in unique_ids if uid.startswith(("U", "W"))]
    return unique_ids, resolvable


def _display_name(user: Dict, uid: str) -> str:
    profile = user.get("profile", {}) or {}
    return (
        profile.get("display_name")
        or profile.get("real_name")
        or user.get("name")
        or uid
    )


def _fetch_name(client: WebClient, uid: str) -> str:
    try:
        resp = handle_rate_limit(client.users_info, user=uid)
    except SlackApiError:
        return uid
    return _display_name((resp or {}).get("user", {}) or {}, uid)


def _to_message(m: Dict) -> Dict:
    return {
        "ts": m.get("ts"),
        "user_id": m.get("user") or m.get("bot_id") or "",
        "text": m.get("text", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Slack スレッドを permalink で取得し、JSON を stdout に出力する"
    )
    parser.add_argument("permalink", type=str, help="Slack スレッドの permalink")
    parser.add_argument("--token", type=str, required=True, help="Slack API トークン")
    args = parser.parse_args()

    channel_id, thread_ts = parse_permalink(args.permalink)
    client = WebClient(token=args.token)

    # 共有の handle_rate_limit を stderr に変えると他のスクリプトの出力も変わるため、
    # stdout を JSON 専用にするのはこの CLI の中だけで行う
    with contextlib.redirect_stdout(sys.stderr):
        replies = fetch_all_thread_replies(
            client, channel_id, thread_ts, skip_parent=False
        )

        messages = [_to_message(m) for m in replies]

        name_map = resolve_user_names(client, [m["user_id"] for m in messages])
    participants = [
        {"user_id": uid, "display_name": name_map[uid]}
        for uid in sorted(name_map.keys())
    ]

    output = {
        "permalink": args.permalink,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "participants": participants,
        "messages": messages,
    }
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
