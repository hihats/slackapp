"""
Slack User utility module

ユーザーIDの解決など、ユーザー関連の共通処理を提供する。
"""

import sys

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def resolve_user_id(client: WebClient, user_input: str) -> str:
    """
    ユーザーIDまたは表示名からユーザーIDを解決する。
    Uで始まる英数字はそのままIDとして返し、
    それ以外は users.list で display_name / real_name をマッチングする。
    """
    # ユーザーID形式（U + 英数字）ならそのまま返す
    if user_input.startswith("U") and user_input[1:].isalnum():
        return user_input

    print(f"Resolving user name '{user_input}' to user ID...")
    target = user_input.lower()

    try:
        cursor = None
        while True:
            response = client.users_list(cursor=cursor, limit=200)
            for member in response.get("members", []):
                if member.get("deleted") or member.get("is_bot"):
                    continue
                profile = member.get("profile", {})
                candidates = [
                    profile.get("display_name_normalized", ""),
                    profile.get("real_name_normalized", ""),
                    member.get("name", ""),
                ]
                if any(c.lower() == target for c in candidates if c):
                    user_id = member["id"]
                    display = profile.get("display_name") or profile.get("real_name") or member.get("name")
                    print(f"Resolved: '{user_input}' -> {user_id} ({display})")
                    return user_id

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
    except SlackApiError as e:
        print(f"Error calling users.list: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Error: User '{user_input}' not found in workspace.", file=sys.stderr)
    sys.exit(1)
