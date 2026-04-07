"""
Slack Conversations API shared module

conversations.history / conversations.replies の呼び出し・ページネーション・レート制限を共通化し、
各スクリプトはフィルタリングと結果加工のみ担当する。
"""

import time
from typing import Dict, Generator, List, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from slack_rate_limit import handle_rate_limit

# conversations.history / conversations.replies は Tier 3 (50 req/min)
_TIER3_INTERVAL = 1.5


def fetch_channel_history(
    client: WebClient,
    channel_id: str,
    oldest: Optional[float] = None,
    latest: Optional[float] = None,
    limit: int = 200,
) -> Generator[List[Dict], None, None]:
    """conversations.history をページベースで呼び出し、1ページ分の messages を yield するジェネレータ。"""
    cursor = None

    while True:
        kwargs = {"channel": channel_id, "limit": limit}
        if oldest is not None:
            kwargs["oldest"] = str(oldest)
        if latest is not None:
            kwargs["latest"] = str(latest)
        if cursor is not None:
            kwargs["cursor"] = cursor

        response = handle_rate_limit(client.conversations_history, **kwargs)

        if not response or not response.get("ok", False):
            break

        messages = response.get("messages", [])
        yield messages

        if response.get("has_more") and response.get("response_metadata", {}).get("next_cursor"):
            cursor = response["response_metadata"]["next_cursor"]
            time.sleep(_TIER3_INTERVAL)
        else:
            break


def fetch_all_channel_history(
    client: WebClient,
    channel_id: str,
    oldest: Optional[float] = None,
    latest: Optional[float] = None,
    limit: int = 200,
) -> List[Dict]:
    """fetch_channel_history をフラット化し、全ページの全メッセージを1つのリストで返す。"""
    all_messages = []
    for messages in fetch_channel_history(client, channel_id, oldest, latest, limit):
        all_messages.extend(messages)
    return all_messages


def fetch_thread_replies(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    oldest: Optional[float] = None,
    latest: Optional[float] = None,
    limit: int = 200,
    skip_parent: bool = True,
) -> Generator[List[Dict], None, None]:
    """conversations.replies をページベースで呼び出し、1ページ分の replies を yield するジェネレータ。

    skip_parent=True の場合、最初のページの先頭メッセージ（親メッセージ）を除外する。
    """
    cursor = None
    is_first_page = True

    while True:
        kwargs = {"channel": channel_id, "ts": thread_ts, "limit": limit}
        if oldest is not None:
            kwargs["oldest"] = str(oldest)
        if latest is not None:
            kwargs["latest"] = str(latest)
        if cursor is not None:
            kwargs["cursor"] = cursor

        response = handle_rate_limit(client.conversations_replies, **kwargs)

        if not response or not response.get("ok", False):
            break

        replies = response.get("messages", [])

        if skip_parent and is_first_page and replies:
            replies = replies[1:]
        # 最初の API 呼び出し後は、replies の有無に関わらず is_first_page を False にする
        is_first_page = False

        yield replies

        if response.get("has_more") and response.get("response_metadata", {}).get("next_cursor"):
            cursor = response["response_metadata"]["next_cursor"]
            time.sleep(_TIER3_INTERVAL)
        else:
            break


def fetch_all_thread_replies(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    oldest: Optional[float] = None,
    latest: Optional[float] = None,
    limit: int = 200,
    skip_parent: bool = True,
) -> List[Dict]:
    """fetch_thread_replies をフラット化し、全ページの全返信を1つのリストで返す。"""
    all_replies = []
    for replies in fetch_thread_replies(client, channel_id, thread_ts, oldest, latest, limit, skip_parent):
        all_replies.extend(replies)
    return all_replies
