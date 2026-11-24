"""Tests for qa_pairs_knowledge module"""

from qa_pairs_knowledge import merge_knowledge
from qa_pairs_markdown import render_markdown


def _pair(thread_ts, question_text="q?", role="answerer", reply_ts=None):
    """reply_ts: 検索に当たった本人の投稿（permalink になる）"""
    reply_ts = reply_ts or thread_ts
    return {
        "role": role, "source": "thread",
        "channel_id": "C1", "channel_name": "general", "thread_ts": thread_ts,
        "permalink": (f"https://x.slack.com/archives/C1/p{reply_ts.replace('.', '')}"
                      f"?thread_ts={thread_ts}"),
        "question": {"ts": thread_ts, "datetime": f"2026-10-0{thread_ts[0]} 10:00:00",
                     "user": "U2", "text": question_text},
        "answers": [{"ts": "9.000001", "datetime": "2026-10-09 10:00:00",
                     "user": "U1", "text": "a", "is_target_user": True}],
    }


def _run_md(*pairs):
    data = {"user_id": "U1", "query": "", "qa_pairs": list(pairs), "standalone_posts": []}
    return render_markdown(data, {}, "期間")


def _headings(md):
    return [line for line in md.splitlines() if line.startswith("#")]


class TestMergeKnowledge:
    def test_new_thread_is_appended_to_its_section(self):
        """蓄積にないスレッドの組は、その節に追加され、組数が増える"""
        knowledge = _run_md(_pair("1.000001", "古い質問"))

        merged, changes = merge_knowledge(knowledge, _run_md(_pair("2.000001", "新しい質問")), "期間")

        assert "## 本人が答えた質問・依頼（2 組）" in merged
        assert merged.index("古い質問") < merged.index("新しい質問")
        assert len(changes) == 1

    def test_same_thread_is_replaced_even_if_link_differs(self):
        """同じスレッドの組は、リンクが違っても新しい内容に差し替わる"""
        knowledge = _run_md(_pair("1.000001", "収集時点の内容"))
        run = _run_md(_pair("1.000001", "取り直した内容", reply_ts="5.000001"))

        merged, _ = merge_knowledge(knowledge, run, "期間")

        assert "## 本人が答えた質問・依頼（1 組）" in merged
        assert "取り直した内容" in merged
        assert "収集時点の内容" not in merged

    def test_note_on_old_pair_survives_replacement(self):
        """差し替えた組でも、古い組の注記は残る"""
        note = "> 更新: 2026-11-01 の判断で更新（[リンク](https://x.slack.com/archives/C1/p3000001)）"
        knowledge = _run_md(_pair("1.000001", "収集時点の内容"))
        heading = next(h for h in _headings(knowledge) if h.startswith("### "))
        knowledge = knowledge.replace(heading, f"{heading}\n{note}")
        run = _run_md(_pair("1.000001", "取り直した内容"))

        merged, _ = merge_knowledge(knowledge, run, "期間")

        assert note in merged
        assert "取り直した内容" in merged

    def test_first_merge_builds_knowledge_without_other_threads(self):
        """蓄積ファイルがないときは、run の Markdown から「その他」を除いて作り、取り込んだ期間を残す"""
        data = {"user_id": "U1", "query": "", "standalone_posts": [],
                "qa_pairs": [_pair("1.000001", "質問"), _pair("2.000001", "雑談")]}
        run = render_markdown(data, {"other_threads": ["C1:2.000001"]}, "2026-10")

        merged, changes = merge_knowledge("", run, "2026-10-01〜2026-10-31")

        assert merged.startswith("# 質問と回答: <@U1>")
        assert "- 収集: 2026-10-01〜2026-10-31" in merged
        assert "その他のスレッド" not in merged
        assert len(changes) == 1

    def test_overlapping_runs_do_not_duplicate_pairs(self):
        """期間が重なった 2 回分を続けて取り込んでも、同じスレッド・同じ投稿の組は 1 つだけ"""
        post = {"ts": "3.000001", "datetime": "2026-10-03 10:00:00",
                "channel_id": "C1", "channel_name": "general", "text": "終わりました",
                "permalink": "https://x.slack.com/archives/C1/p3000001"}
        data = {"user_id": "U1", "query": "", "standalone_posts": [post],
                "qa_pairs": [_pair("1.000001", "スレッドの質問")]}
        judgement = {"channel_context_pairs": [
            {"post": "C1:3.000001",
             "question": {"datetime": "2026-10-03 09:00:00", "user": "U2", "text": "直前の質問"}}]}
        run = render_markdown(data, judgement, "期間")

        once, _ = merge_knowledge("", run, "期間")
        twice, changes = merge_knowledge(once, run, "期間")

        assert "## 本人が答えた質問・依頼（2 組）" in twice
        assert twice.count("スレッドの質問") == 1
        assert twice.count("直前の質問") == 1
        assert changes == []
