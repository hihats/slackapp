"""
Slack Search API shared module

search.messages API の呼び出し・ページネーション・レート制限を共通化し、
各スクリプトはクエリ構築と結果加工のみ担当する。
"""

import sys
import time
from typing import Dict, Generator, List, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


class SlackSearchError(Exception):
    """search.messages API 固有のエラー"""
    pass


def handle_rate_limit(func, *args, max_retries=5, base_delay=1, **kwargs):
    """レート制限に対応するためのラッパー関数"""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                if attempt == max_retries - 1:
                    print(f"最大再試行回数に達しました: {e}")
                    raise
                if e.response.status_code == 429:
                    retry_after = int(e.response.headers.get("Retry-After", 30))
                    print(f"レート制限に達しました。{retry_after}秒待機します... (試行 {attempt + 1}/{max_retries})")
                    time.sleep(retry_after)
            else:
                raise

    return None


def build_query(
    keyword: Optional[str] = None,
    channel_id: Optional[str] = None,
    after_date: Optional[str] = None,
    extra: Optional[str] = None,
) -> str:
    """Slack search.messages 用のクエリ文字列を組み立てる"""
    parts = []
    if channel_id:
        parts.append(f"in:{channel_id}")
    if keyword:
        parts.append(f'"{keyword}"')
    if extra:
        parts.append(extra)
    if after_date:
        parts.append(f"after:{after_date}")
    return " ".join(parts)


def search_messages(
    client: WebClient,
    query: str,
    sort: str = "timestamp",
    sort_dir: str = "asc",
    max_pages: int = 50,
) -> Generator[List[Dict], None, None]:
    """
    search.messages API をページベースで呼び出し、
    1ページ分の matches を yield するジェネレータ。
    """
    page = 1
    has_more = True

    try:
        while has_more:
            response = handle_rate_limit(
                client.search_messages,
                query=query,
                sort=sort,
                sort_dir=sort_dir,
                count=100,
                page=page,
            )

            if not response or not response["ok"]:
                break

            matches = response.get("messages", {}).get("matches", [])
            pagination = response.get("messages", {}).get("pagination", {})

            page_count = pagination.get("page_count", 1)
            current_page = pagination.get("page", page)

            yield matches

            if current_page < page_count and page < max_pages:
                page += 1
                time.sleep(1.5)  # Tier 3: 50リクエスト/分
            else:
                has_more = False

    except SlackApiError as e:
        if e.response["error"] == "missing_scope":
            raise SlackSearchError(
                "Token needs 'search:read' scope for Search API. "
                "Please ensure your token has the search:read scope enabled."
            )
        raise


def search_all_messages(
    client: WebClient,
    query: str,
    sort: str = "timestamp",
    sort_dir: str = "asc",
    max_pages: int = 50,
) -> List[Dict]:
    """search_messages をフラット化し、全ページの全 match を1つのリストで返す。"""
    all_matches = []
    for matches in search_messages(client, query, sort, sort_dir, max_pages):
        all_matches.extend(matches)
    return all_matches
