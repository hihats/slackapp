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
            # Slack が ratelimited を返した場合はリトライする
            if e.response["error"] == "ratelimited":
                if attempt == max_retries - 1:
                    print(f"最大再試行回数に達しました: {e}")
                    raise

                # 通常は 429 + Retry-After が返る想定だが、
                # status_code が無い / 429 でない場合にもフォールバックで待機する
                status_code = getattr(e.response, "status_code", None)
                if status_code == 429:
                    retry_after = int(e.response.headers.get("Retry-After", 30))
                    print(
                        f"レート制限に達しました。{retry_after}秒待機します... "
                        f"(試行 {attempt + 1}/{max_retries})"
                    )
                    time.sleep(retry_after)
                else:
                    # フォールバックの指数バックオフ
                    fallback_delay = base_delay * (2 ** attempt)
                    print(
                        f"レート制限 (非 429 または status_code 不明) に達しました。"
                        f"{fallback_delay}秒待機します... (試行 {attempt + 1}/{max_retries})"
                    )
                    time.sleep(fallback_delay)
            else:
                raise

    # ここに到達するのは通常想定していないが、安全のため明示的に例外を投げる
    raise SlackApiError(
        "レート制限ハンドラで最大再試行回数に達しましたが、SlackApiError が再送時に伝播しませんでした。",
        response=None,
    )


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
        if channel_id.startswith("C") and channel_id[1:].isalnum():
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
