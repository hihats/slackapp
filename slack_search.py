"""
Slack Search API shared module

search.messages API の呼び出し・ページネーション・レート制限を共通化し、
各スクリプトはクエリ構築と結果加工のみ担当する。
"""

import time
from typing import Dict, Generator, List, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from slack_rate_limit import handle_rate_limit


class SlackSearchError(Exception):
    """search.messages API 固有のエラー"""
    pass


def build_query(
    keyword: Optional[str] = None,
    channel_id: Optional[str] = None,
    after_date: Optional[str] = None,
    extra: Optional[str] = None,
    exact_match: bool = True,
) -> str:
    """Slack search.messages 用のクエリ文字列を組み立てる

    exact_match=True の場合、keyword を引用符で囲みフレーズ一致にする。
    短いキーワードや部分一致させたい場合は False を指定する。
    """
    parts = []
    if channel_id:
        # チャンネルIDは <#ID> 形式でないと search.messages で認識されない
        if channel_id[0] in ("C", "G") and channel_id[1:].isalnum():
            parts.append(f"in:<#{channel_id}>")
        else:
            parts.append(f"in:{channel_id}")
    if keyword:
        # in: と組み合わせたとき大文字混在だとヒットしないことがある Slack 側の挙動を回避
        kw = keyword.lower()
        parts.append(f'"{kw}"' if exact_match else kw)
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

            if not response or not response.get("ok", False):
                # handle_rate_limit が None を返した、または Slack API が ok=False を返した場合は
                # サイレントにページネーションを終了せず、呼び出し側に明示的に失敗を伝える
                error_msg = "Failed to fetch search results from Slack API."
                if response and isinstance(response, dict):
                    error_detail = response.get("error")
                    if error_detail:
                        error_msg = f"{error_msg} error={error_detail}"
                raise SlackSearchError(error_msg)

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
