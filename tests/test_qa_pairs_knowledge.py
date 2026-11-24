"""Tests for qa_pairs_knowledge module"""

import pytest

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


def _knowledge_md(*pairs):
    """merge が作る蓄積ファイル（「その他」の節はない）。"""
    return merge_knowledge("", _run_md(*pairs), "期間")[0]


def _headings(md):
    return [line for line in md.splitlines() if line.startswith("#")]


class TestMergeKnowledge:
    def test_new_thread_is_appended_to_its_section(self):
        """蓄積にないスレッドの組は、その節に追加され、組数が増える"""
        knowledge = _knowledge_md(_pair("1.000001", "古い質問"))

        merged, changes = merge_knowledge(knowledge, _run_md(_pair("2.000001", "新しい質問")), "期間")

        assert "## 本人が答えた質問・依頼（2 組）" in merged
        assert merged.index("古い質問") < merged.index("新しい質問")
        assert len(changes) == 1

    def test_same_thread_is_replaced_keeping_stored_link(self):
        """同じスレッドの組は、リンクが違っても新しい内容に差し替わり、見出しのリンクは蓄積時のまま"""
        knowledge = _knowledge_md(_pair("1.000001", "収集時点の内容"))
        run = _run_md(_pair("1.000001", "取り直した内容", reply_ts="5.000001"))

        merged, _ = merge_knowledge(knowledge, run, "期間")

        assert "## 本人が答えた質問・依頼（1 組）" in merged
        assert "取り直した内容" in merged
        assert "収集時点の内容" not in merged
        assert "/p1000001?thread_ts=1.000001" in merged
        assert "/p5000001" not in merged

    def test_link_with_query_in_other_order_is_the_same_thread(self):
        """クエリの順が違うリンクでも、同じスレッドの組として差し替わる"""
        knowledge = _knowledge_md(_pair("1.000001", "収集時点の内容"))
        pair = _pair("1.000001", "取り直した内容", reply_ts="5.000001")
        pair["permalink"] = "https://x.slack.com/archives/C1/p5000001?cid=C1&thread_ts=1.000001"

        merged, _ = merge_knowledge(knowledge, _run_md(pair), "期間")

        assert "## 本人が答えた質問・依頼（1 組）" in merged
        assert "取り直した内容" in merged
        assert "収集時点の内容" not in merged

    def test_link_only_change_is_not_reported(self):
        """内容が同じでリンクだけ違う組は、追加・変更した組に入らない"""
        knowledge = _knowledge_md(_pair("1.000001", "同じ内容"))
        run = _run_md(_pair("1.000001", "同じ内容", reply_ts="5.000001"))

        _, changes = merge_knowledge(knowledge, run, "期間")

        assert changes == []

    def test_quoted_note_in_question_is_not_carried_over(self):
        """質問本文中の「> 更新:」の行は注記として引き継がれない"""
        knowledge = _knowledge_md(_pair("1.000001", "本文\n> 更新: 引用した行"))
        run = _run_md(_pair("1.000001", "本文（編集済み）"))

        merged, _ = merge_knowledge(knowledge, run, "期間")

        assert "> 更新: 引用した行" not in merged

    def test_section_heading_in_question_does_not_drop_pairs(self):
        """質問本文に節の見出しと同じ行があっても、組は消えない"""
        knowledge = _knowledge_md(_pair("1.000001", "前の組"))
        run = _run_md(_pair("2.000001", "例:\n## 本人が答えた質問・依頼（1 組）"))

        merged, _ = merge_knowledge(knowledge, run, "期間")

        assert "## 本人が答えた質問・依頼（2 組）" in merged

    def test_pair_moved_to_another_section_is_kept_once_with_note(self):
        """スレッド外の回答として蓄積した投稿が本人の質問スレッドとして取り直されたら、
        組は新しい節に 1 つだけ残り、注記は見出しの次の行に残る"""
        note = "> 更新: 2026-11-01 の判断で更新（[リンク](https://x.slack.com/archives/C1/p4000001)）"
        post = {"ts": "3.000001", "datetime": "2026-10-03 10:00:00",
                "channel_id": "C1", "channel_name": "general", "text": "回答",
                "permalink": "https://x.slack.com/archives/C1/p3000001"}
        data = {"user_id": "U1", "query": "", "standalone_posts": [post], "qa_pairs": []}
        judgement = {"channel_context_pairs": [
            {"post": "C1:3.000001",
             "question": {"datetime": "2026-10-03 09:00:00", "user": "U2", "text": "直前の質問"}}]}
        knowledge, _ = merge_knowledge("", render_markdown(data, judgement, "期間"), "期間")
        heading = next(h for h in _headings(knowledge) if h.startswith("### "))
        knowledge = knowledge.replace(heading, f"{heading}\n{note}")
        run = _run_md(_pair("3.000001", "スレッドになった質問", role="asker"))

        merged, _ = merge_knowledge(knowledge, run, "期間")

        lines = merged.splitlines()
        assert "## 本人が答えた質問・依頼（0 組）" in merged
        assert "## 本人の質問・依頼と回答（1 組）" in merged
        assert lines[lines.index(note) - 1].startswith("### ")

    def test_section_heading_after_line_separator_does_not_drop_pairs(self):
        """質問本文で U+2028 の後に節の見出しと同じ文字列があっても、組は消えない"""
        knowledge = _knowledge_md(_pair("1.000001", "前の組"))
        run = _run_md(_pair("2.000001", "例: ## 本人が答えた質問・依頼（1 組）"))

        merged, _ = merge_knowledge(knowledge, run, "期間")

        assert "## 本人が答えた質問・依頼（2 組）" in merged

    def test_unescaped_heading_in_old_markdown_stops_merge(self):
        """エスケープのない旧版の Markdown で、本文に節の見出しと同じ行があると、組を捨てずに止まる"""
        run = _run_md(_pair("1.000001", "例:\n## 本人が答えた質問・依頼（1 組）"))
        run = run.replace("\\## ", "## ")

        with pytest.raises(ValueError):
            merge_knowledge("", run, "期間")

    def test_others_heading_in_old_knowledge_stops_merge(self):
        """旧版の蓄積で、質問本文に「その他」の節の見出しと同じ行があると、組を削らずに止まる"""
        run = _run_md(_pair("1.000001", "例:\n## その他のスレッド（0 件）\n続き"))
        knowledge, _ = merge_knowledge("", run, "期間")
        knowledge = knowledge.replace("\\## ", "## ")

        with pytest.raises(ValueError):
            merge_knowledge(knowledge, _run_md(), "期間")

    def test_post_collected_as_both_thread_and_standalone_is_kept_once(self):
        """1 回分の収集結果で同じ投稿がスレッドとスレッド外の両方にあると、スレッドの組だけ残る"""
        post = {"ts": "3.000001", "datetime": "2026-10-03 10:00:00",
                "channel_id": "C1", "channel_name": "general", "text": "回答",
                "permalink": "https://x.slack.com/archives/C1/p3000001"}
        data = {"user_id": "U1", "query": "", "standalone_posts": [post],
                "qa_pairs": [_pair("3.000001", "スレッドの質問", role="asker")]}
        judgement = {"channel_context_pairs": [
            {"post": "C1:3.000001",
             "question": {"datetime": "2026-10-03 09:00:00", "user": "U2", "text": "直前の質問"}}]}

        merged, _ = merge_knowledge("", render_markdown(data, judgement, "期間"), "期間")

        assert "## 本人が答えた質問・依頼（0 組）" in merged
        assert "## 本人の質問・依頼と回答（1 組）" in merged

    def test_crlf_question_can_be_merged_after_file_round_trip(self, tmp_path):
        """改行が CRLF の質問本文でも、ファイルに書いて読み直した Markdown を取り込める"""
        path = tmp_path / "qa_pairs.md"
        path.write_text(_run_md(_pair("1.000001", "例:\r\n## 本人が答えた質問・依頼（1 組）\r\n続き")))

        merged, _ = merge_knowledge("", path.read_text(), "期間")

        assert "続き" in merged

    def test_post_is_kept_when_its_thread_is_judged_other(self):
        """スレッドを「その他」に回しても、親投稿をチャンネル内の回答に採った組は蓄積に残る"""
        post = {"ts": "3.000001", "datetime": "2026-10-03 10:00:00",
                "channel_id": "C1", "channel_name": "general", "text": "対応しました",
                "permalink": "https://x.slack.com/archives/C1/p3000001"}
        data = {"user_id": "U1", "query": "", "standalone_posts": [post],
                "qa_pairs": [_pair("3.000001", "対応しました")]}
        judgement = {"other_threads": ["C1:3.000001"], "channel_context_pairs": [
            {"post": "C1:3.000001",
             "question": {"datetime": "2026-10-03 09:00:00", "user": "U2", "text": "先行する依頼"}}]}

        merged, _ = merge_knowledge("", render_markdown(data, judgement, "期間"), "期間")

        assert "## 本人が答えた質問・依頼（1 組）" in merged
        assert "先行する依頼" in merged

    def test_knowledge_with_duplicated_pair_stops_merge(self):
        """蓄積に同じスレッド・投稿の組が 2 つあると、注記を捨てずに止まる"""
        post = {"ts": "3.000001", "datetime": "2026-10-03 10:00:00",
                "channel_id": "C1", "channel_name": "general", "text": "回答",
                "permalink": "https://x.slack.com/archives/C1/p3000001"}
        data = {"user_id": "U1", "query": "", "standalone_posts": [post],
                "qa_pairs": [_pair("3.000001", "スレッドの質問", role="asker")]}
        judgement = {"channel_context_pairs": [
            {"post": "C1:3.000001",
             "question": {"datetime": "2026-10-03 09:00:00", "user": "U2", "text": "直前の質問"}}]}
        # 修正前の merge が作った、同じキーの組が 2 節にある蓄積
        knowledge = render_markdown(data, judgement, "期間").split("\n## その他のスレッド")[0]

        with pytest.raises(ValueError):
            merge_knowledge(knowledge, _run_md(), "期間")

    def test_code_in_question_is_kept_as_is(self):
        """質問本文のコード例の行（#!/bin/sh など）は書き換えられない"""
        run = _run_md(_pair("1.000001", "例:\n```\n#!/bin/sh\n# コメント\n```"))

        merged, _ = merge_knowledge("", run, "期間")

        assert "\n#!/bin/sh\n# コメント\n" in merged

    def test_note_on_old_pair_survives_replacement(self):
        """差し替えた組でも、古い組の注記は見出しの次の行に残る"""
        note = "> 更新: 2026-11-01 の判断で更新（[リンク](https://x.slack.com/archives/C1/p3000001)）"
        knowledge = _knowledge_md(_pair("1.000001", "収集時点の内容"))
        heading = next(h for h in _headings(knowledge) if h.startswith("### "))
        knowledge = knowledge.replace(heading, f"{heading}\n{note}")
        run = _run_md(_pair("1.000001", "取り直した内容"))

        merged, _ = merge_knowledge(knowledge, run, "期間")

        assert f"{heading}\n{note}" in merged
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
