"""Tests for qa_pairs_markdown module"""

import pytest

from qa_pairs_markdown import build_index, render_markdown

PERMALINK = "https://x.slack.com/archives/C1/p100000001"


def _pair(role="answerer", question_text="q?", answers=None):
    return {
        "role": role, "source": "thread",
        "channel_id": "C1", "channel_name": "general",
        "thread_ts": "100.000001",
        "permalink": PERMALINK,
        "question": {"ts": "100.000001", "datetime": "2026-10-06 14:03:42",
                     "user": "U2", "text": question_text},
        "answers": answers if answers is not None else [
            {"ts": "200.000002", "datetime": "2026-10-06 14:09:36",
             "user": "U1", "text": "a", "is_target_user": True},
        ],
    }


def _data(pairs=(), posts=()):
    return {"user_id": "U1", "query": "from:<@U1>",
            "qa_pairs": list(pairs), "standalone_posts": list(posts)}


# --- build_index ---


class TestBuildIndex:
    def test_thread_shows_key_and_full_question_text(self):
        """スレッドはキーと親の本文を全文載せる"""
        text = "<https://drive.example/x>\n" + "このフォルダ名、変えても大丈夫です？" * 20

        index = build_index(_data([_pair(question_text=text)]))

        assert "C1:100.000001" in index
        assert text in index

    def test_answerer_shows_head_of_first_own_reply(self):
        """answerer の組は、本人の最初の返信の冒頭 100 字を載せる"""
        answers = [
            {"ts": "150.000001", "datetime": "2026-10-06 14:05:00",
             "user": "U3", "text": "他の人の返信", "is_target_user": False},
            {"ts": "200.000002", "datetime": "2026-10-06 14:09:36",
             "user": "U1", "text": "対" * 150, "is_target_user": True},
        ]

        index = build_index(_data([_pair(answers=answers)]))

        assert "対" * 100 in index
        assert "対" * 101 not in index

    def test_standalone_post_shows_key_and_text(self):
        """スレッド外の投稿もキーと本文を載せる"""
        post = {"ts": "300.000003", "datetime": "2026-10-06 20:35:32",
                "channel_id": "C1", "channel_name": "general",
                "text": "終わりました", "permalink": None, "is_thread_reply": False}

        index = build_index(_data(posts=[post]))

        assert "C1:300.000003" in index
        assert "終わりました" in index

    def test_standalone_post_shows_full_datetime_and_permalink(self):
        """スレッド外の投稿は、組を作るのに要る秒までの日時とリンクも載せる"""
        post = {"ts": "300.000003", "datetime": "2026-10-06 20:35:32",
                "channel_id": "C1", "channel_name": "general", "text": "終わりました",
                "permalink": "https://x.slack.com/archives/C1/p300000003",
                "is_thread_reply": False}

        index = build_index(_data(posts=[post]))

        assert "2026-10-06 20:35:32" in index
        assert "https://x.slack.com/archives/C1/p300000003" in index


    def test_slack_escaped_symbols_are_restored(self):
        """索引の本文も、Slack がエスケープした記号を元に戻して載せる"""
        answers = [
            {"ts": "200.000002", "datetime": "2026-10-06 14:09:36",
             "user": "U1", "text": "&gt; 対応しました", "is_target_user": True},
        ]
        post = {"ts": "300.000003", "datetime": "2026-10-06 20:35:32",
                "channel_id": "C1", "channel_name": "general", "text": "A &amp; B",
                "permalink": None, "is_thread_reply": False}
        data = _data([_pair(question_text="A &lt; B", answers=answers)], [post])

        index = build_index(data)

        assert "A < B" in index
        assert "> 対応しました" in index
        assert "A & B" in index

# --- render_markdown ---


class TestRenderMarkdown:
    def test_other_thread_shows_only_link_in_others_section(self):
        """その他に回したスレッドは本文を載せず、「その他のスレッド」にリンクだけ出す"""
        data = _data([_pair(question_text="日報です")])

        md = render_markdown(data, {"other_threads": ["C1:100.000001"]}, "2026-10-06")

        assert "日報です" not in md
        assert PERMALINK in md.split("## その他のスレッド")[1]

    def test_pairs_are_grouped_by_role_with_counts(self):
        """role ごとに節を分け、組数を出す"""
        asked = {**_pair(role="asker", question_text="質問した件"), "thread_ts": "110.000001"}
        data = _data([_pair(role="answerer", question_text="回答した件"), asked])

        md = render_markdown(data, {}, "2026-10-06")

        answerer_part = md.split("## 本人が答えた質問・依頼（1 組）")[1].split("## 本人の質問・依頼と回答")[0]
        asker_part = md.split("## 本人の質問・依頼と回答（1 組）")[1].split("## その他のスレッド")[0]
        assert "回答した件" in answerer_part
        assert "質問した件" in asker_part

    def test_only_target_user_answers_are_bold(self):
        """回答欄では本人の発言だけを太字にする"""
        answers = [
            {"ts": "150.000001", "datetime": "2026-10-06 14:05:00",
             "user": "U3", "text": "他の人の返信", "is_target_user": False},
            {"ts": "200.000002", "datetime": "2026-10-06 14:09:36",
             "user": "U1", "text": "本人の返信", "is_target_user": True},
        ]

        md = render_markdown(_data([_pair(answers=answers)]), {}, "2026-10-06")

        assert "- **<@U1> (2026-10-06 14:09:36): 本人の返信**" in md
        assert "- <@U3> (2026-10-06 14:05:00): 他の人の返信" in md

    def test_channel_context_pair_is_in_answerer_section(self):
        """スレッド外で答えた組は「本人が答えた質問・依頼」に入る"""
        pair = {**_pair(role="answerer", question_text="これ使えますか？"),
                "source": "channel_context"}

        md = render_markdown(_data(), {"channel_context_pairs": [pair]}, "2026-10-06")

        answerer_part = md.split("## 本人が答えた質問・依頼（1 組）")[1].split("## 本人の質問・依頼と回答")[0]
        assert "これ使えますか？" in answerer_part

    def test_unknown_other_thread_key_is_an_error(self):
        """other_threads に collect の結果にないキーがあればエラーにする"""
        with pytest.raises(ValueError, match="C1:999.000001"):
            render_markdown(_data([_pair()]), {"other_threads": ["C1:999.000001"]}, "2026-10-06")

    def test_slack_escaped_symbols_are_restored(self):
        """Slack がエスケープした & < > は元の記号に戻して載せる"""
        answers = [
            {"ts": "200.000002", "datetime": "2026-10-06 14:09:36",
             "user": "U3", "text": "&gt; 引用 &amp;lt;", "is_target_user": False},
        ]
        data = _data([_pair(question_text="A &lt; B &amp; C", answers=answers)])

        md = render_markdown(data, {}, "2026-10-06")

        assert "A < B & C" in md
        assert "> 引用 &lt;" in md

    def test_answer_line_breaks_become_single_space(self):
        """回答を 1 行にするとき、空行を含む改行や続く空白は 1 つの空白にまとめる"""
        answers = [
            {"ts": "200.000002", "datetime": "2026-10-06 14:11:23",
             "user": "U3", "text": "大丈夫です！\n\nClaude Code  にする", "is_target_user": False},
        ]

        md = render_markdown(_data([_pair(answers=answers)]), {}, "2026-10-06")

        assert "- <@U3> (2026-10-06 14:11:23): 大丈夫です！ Claude Code にする\n" in md
