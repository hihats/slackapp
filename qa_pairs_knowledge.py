"""
qa-pairs の Markdown を、ユーザー×チャンネルの蓄積ファイルに積み上げる。

render 後に手で入れた省略は collect の JSON にないため、JSON から作り直さず
Markdown を組（### の見出し）単位でまとめる。
"""

import re
from itertools import takewhile

from qa_pairs_markdown import SECTIONS
from user_posts import permalink_thread_ts

TITLES = [title for _, title in SECTIONS]
OTHERS = "その他のスレッド"
# 質問の本文は複数行で "# 要旨" のような行も含むため、見出しは形ごと照合する
SECTION_HEADING = re.compile(
    rf"^## ({'|'.join(TITLES + [OTHERS])})（\d+ (?:組|件)）$")
PAIR_HEADING = re.compile(r"^### .+ / \d{4}-\d{2}-\d{2} [\d:]+ （\[リンク\]\(\S+\)）$")
LINK_PART = re.compile(r"（\[リンク\]\((\S+)\)）$")
# 検索に当たった本人の投稿のリンクなので、取り直すと変わる。スレッドで突き合わせる
LINK_PATH = re.compile(r"/archives/([^/?]+)/p(\d+)")
NOTE_PREFIX = "> 更新:"


def _blocks(lines):
    """行を、組の見出しごとのかたまりに分ける。最初の見出しより前（「なし」など）は捨てる。"""
    blocks = []
    for line in lines:
        if PAIR_HEADING.match(line):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
    return ["\n".join(block).strip() for block in blocks]


def _sections(md):
    """節の題 → その節の組のリスト。"""
    grouped, current = {}, None
    for line in md.splitlines():
        match = SECTION_HEADING.match(line)
        if match:
            current = match.group(1)
            grouped[current] = []
        elif current:
            grouped[current].append(line)
    return {title: _blocks(lines) for title, lines in grouped.items()}


def _key(block):
    """組の見出しのリンクから (チャンネル ID, スレッドまたは投稿の ts) を取る。"""
    url = LINK_PART.search(block.splitlines()[0]).group(1)
    channel_id, p_ts = LINK_PATH.search(url).groups()
    thread_ts = permalink_thread_ts({"permalink": url})
    return channel_id, thread_ts or f"{p_ts[:-6]}.{p_ts[-6:]}"


def _notes(block):
    """見出しの次の行から続く注記の行。"""
    # 質問の本文にも引用の行があるため、組の中全体からは探さない
    lines = block.splitlines()[1:]
    return list(takewhile(lambda line: line.startswith(NOTE_PREFIX), lines))


def _with_notes(new_block, old_block):
    """古い組の注記を、新しい組の見出しの次の行に入れる。"""
    notes = [note for note in _notes(old_block) if note not in _notes(new_block)]
    heading, _, rest = new_block.partition("\n")
    return "\n".join([heading, *notes, rest])


def _keep_link(new_block, old_block):
    """新しい組の見出しのリンクを、古い組のリンクに置き換える。"""
    # 注記は古い組のリンクを指すため、見出しのリンクを変えると注記から辿れなくなる
    if not old_block:
        return new_block
    old_link = LINK_PART.search(old_block.splitlines()[0]).group(0)
    heading, sep, rest = new_block.partition("\n")
    return LINK_PART.sub(lambda _: old_link, heading) + sep + rest


def _merge_blocks(old_blocks, new_blocks):
    """同じキーは新しい組で上書きし（注記は引き継ぐ）、ないものは末尾に足す。
    新しく入った組と中身が変わった組も返す。"""
    merged = {_key(block): block for block in old_blocks}
    changed = []
    for block in new_blocks:
        key = _key(block)
        old = merged.get(key, "")
        updated = _with_notes(_keep_link(block, old), old)
        if old != updated:
            changed.append(updated.splitlines()[0])
        merged[key] = updated
    return list(merged.values()), changed


def _render(title, sections):
    parts = [title] + [f"## {name}（{len(sections[name])} 組）\n\n"
                       + ("\n\n".join(sections[name]) or "なし")
                       for name in TITLES]
    return "\n\n".join(parts) + "\n"


def _header(md):
    """最初の節の見出しより前（タイトルと収集の記録）の、空でない行。"""
    lines = []
    for line in md.splitlines():
        if SECTION_HEADING.match(line):
            break
        if line.strip():
            lines.append(line)
    return lines


def _section_of(sections):
    """組のキー → その組がある節の題。"""
    return {_key(block): name for name, blocks in sections.items() for block in blocks}


def _move_across_sections(old, new):
    """新しい run で別の節に出た組を、古い節からその節へ移す。"""
    # スレッド外の回答に後から返信が付くと、同じキーの組が本人の質問の節で取り直される
    section_of = _section_of(new)
    moved = {name: [] for name in TITLES}
    for name, blocks in old.items():
        for block in blocks:
            moved[section_of.get(_key(block), name)].append(block)
    return moved


def _merge_sections(old, new):
    """節ごとに組をまとめ、(節 → 組, 追加・変更した組の見出し) を返す。"""
    old = _move_across_sections(old, new)
    merged, changes = {}, []
    for name in TITLES:
        merged[name], changed = _merge_blocks(old.get(name, []), new.get(name, []))
        changes += changed
    return merged, changes


def merge_knowledge(knowledge_md, run_md, period):
    """蓄積ファイルに run の組を積み上げ、結果と追加・差し替えした組の見出しを返す。"""
    merged, changes = _merge_sections(_sections(knowledge_md), _sections(run_md))
    # 蓄積が空なら run のタイトルだけ使う（run に収集の記録はない）
    header = (_header(knowledge_md) or _header(run_md)[:1]) + [f"- 収集: {period}"]
    return _render("\n".join(header), merged), changes
