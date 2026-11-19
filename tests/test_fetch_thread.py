"""Unit tests for summarize-thread fetch_thread CLI"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from slack_sdk.errors import SlackApiError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / ".claude" / "skills" / "summarize-thread"))
import fetch_thread  # noqa: E402

PERMALINK = "https://slack.com/archives/C1/p1700000000000100?thread_ts=1700000000.000100"


def _ratelimited():
    response = MagicMock(status_code=429, headers={"Retry-After": "0"})
    response.__getitem__.side_effect = {"error": "ratelimited"}.__getitem__
    return SlackApiError("ratelimited", response)


@patch("slack_rate_limit.time.sleep")
@patch("fetch_thread.time.sleep")
@patch("fetch_thread.fetch_all_thread_replies")
@patch("fetch_thread.WebClient")
def test_stdout_is_json_even_after_rate_limit_retry(
        web_client, replies, _sleep, _retry_sleep, capsys):
    """users.info が一度レート制限を返しても、標準出力は JSON として読める"""
    replies.return_value = [{"ts": "1700000000.000100", "user": "U1", "text": "質問"}]
    web_client.return_value.users_info.side_effect = [
        _ratelimited(),
        {"user": {"profile": {"display_name": "hihats"}}},
    ]

    with patch.object(sys, "argv", ["fetch_thread.py", PERMALINK, "--token", "x"]):
        fetch_thread.main()

    output = json.loads(capsys.readouterr().out)
    assert output["participants"] == [{"user_id": "U1", "display_name": "hihats"}]
