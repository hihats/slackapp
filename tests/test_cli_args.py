"""Unit tests for cli_args module"""

from argparse import Namespace

from cli_args import redact_args


def test_token_value_is_hidden_and_other_args_remain():
    """トークンの値は伏せられ、他の引数はそのまま残る"""
    args = Namespace(token="xoxp-secret", channel="C1", days=7)

    shown = redact_args(args)

    assert "xoxp-secret" not in str(shown)
    assert shown == {"token": "***", "channel": "C1", "days": 7}
