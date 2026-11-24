"""
CLI 引数の表示を共通化する。
"""

SECRET_KEYS = ("token",)


def redact_args(args):
    """秘密の引数を伏せた dict を返す。"""
    return {key: "***" if key in SECRET_KEYS else value
            for key, value in vars(args).items()}
