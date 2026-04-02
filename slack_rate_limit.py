"""
Slack API rate limit handling shared module

全 Slack API 呼び出しで共通利用するレート制限ハンドラ。
Retry-After ヘッダーがあればその値を使用し、なければ指数バックオフで待機する。
"""

import time

from slack_sdk.errors import SlackApiError


def handle_rate_limit(func, *args, max_retries=5, base_delay=1, **kwargs):
    """レート制限に対応するためのラッパー関数

    Retry-After ヘッダーがある場合はその値を使用し、
    ない場合は base_delay を基にした指数バックオフ (base_delay * 2^attempt) を適用する。
    """
    status_code = None
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except SlackApiError as e:
            # Slack が ratelimited を返した場合はリトライする
            if e.response["error"] == "ratelimited":
                if attempt == max_retries - 1:
                    print(f"最大再試行回数に達しました: {e}")
                    raise
                status_code = getattr(e.response, "status_code", None)
                if status_code == 429:
                    backoff = base_delay * (2 ** attempt)
                    retry_after = int(e.response.headers.get("Retry-After", backoff))
                    print(
                        f"レート制限に達しました。{retry_after}秒待機します... "
                        f"(試行 {attempt + 1}/{max_retries})"
                    )
                    time.sleep(retry_after)
                elif status_code is None or status_code >= 500:
                    fallback_delay = base_delay * (2 ** attempt)
                    print(
                        f"サーバーエラー (status_code={status_code})。"
                        f"{fallback_delay}秒待機します... (試行 {attempt + 1}/{max_retries})"
                    )
                    time.sleep(fallback_delay)
                else:
                    # 4xx (429以外) はリトライしても解決しない
                    raise
            else:
                raise

    raise SlackApiError(
        f"最大再試行回数 ({max_retries}) に達しました。(status_code={status_code})",
        response=None,
    )
