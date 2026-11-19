"""
collect の出力から、判定用の索引と Markdown を作る。

Slack には触らない。Claude が中間 JSON をそのまま読むと、
JSON の構造の分だけ文脈が埋まるため、ここで整形する。
"""

# 依頼かどうかは「対応しました」など返信の書き出しで分かる。全文は索引が重くなるため載せない
OWN_REPLY_HEAD = 100
SECTIONS = [("answerer", "本人が答えた質問・依頼"), ("asker", "本人の質問・依頼と回答")]


def thread_key(pair):
    """索引と判定ファイルで共通に使うスレッドのキー。"""
    return f"{pair['channel_id']}:{pair['thread_ts']}"


def post_key(post):
    """索引と判定ファイルで共通に使う、スレッド外の投稿のキー。"""
    return f"{post['channel_id']}:{post['ts']}"


def _first_own_reply(pair):
    own = next((a["text"] for a in pair["answers"] if a["is_target_user"]), "")
    # 先に切ると &amp; の途中で切れて戻せないため、戻してから切る
    return _unescape(own)[:OWN_REPLY_HEAD]


def _unescape(text):
    """Slack がエスケープした & < > を元に戻す。"""
    # html.unescape は本文にそのまま書かれた &copy; などまで変えるため使わない。
    # &amp; を最後に戻すのは、&amp;lt; を < まで戻さないため
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _index_thread(pair):
    question = pair["question"]
    own = sum(a["is_target_user"] for a in pair["answers"])
    header = (f"## T {thread_key(pair)} | {pair['role']} | #{pair['channel_name']}"
              f" | {question['datetime'][:16]}"
              f" | 返信 {len(pair['answers'])}（本人 {own}）")
    # 依頼や質問が本文の後半にあることがあるため、切り詰めない
    lines = [header, _unescape(question["text"])]
    if pair["role"] == "answerer":
        lines.append(f"> 本人の最初の返信: {_first_own_reply(pair)}")
    return "\n".join(lines)


def _index_post(post):
    header = f"## S {post_key(post)} | #{post['channel_name']} | {post['datetime'][:16]}"
    return f"{header}\n{_unescape(post['text'])}"


def build_index(data):
    """判定用に、スレッド（T）とスレッド外の投稿（S）を見出しと本文で並べる。"""
    blocks = ([_index_thread(p) for p in data["qa_pairs"]]
              + [_index_post(p) for p in data["standalone_posts"]])
    return "\n\n".join(blocks) + "\n"


def _render_answer(answer):
    # 太字や箇条書きが改行で切れないよう 1 行にする。
    # 改行を 1 文字ずつ置き換えると空行で空白が重なるため、空白類の連なりごとにまとめる
    text = " ".join(_unescape(answer["text"]).split())
    line = f"<@{answer['user']}> ({answer['datetime']}): {text}"
    return f"- **{line}**" if answer["is_target_user"] else f"- {line}"


def _render_pair(pair):
    question = pair["question"]
    answers = "\n".join(_render_answer(a) for a in pair["answers"])
    return (f"### {pair['channel_name']} / {question['datetime']} （[リンク]({pair['permalink']})）\n"
            f"**Q** <@{question['user']}>: {_unescape(question['text'])}\n\n**A**\n{answers}")


def _render_section(title, pairs):
    body = "\n\n".join(_render_pair(p) for p in pairs) or "なし"
    return f"## {title}（{len(pairs)} 組）\n\n{body}"


def _render_others(pairs):
    lines = [f"- {p['channel_name']} [リンク]({p['permalink']})" for p in pairs]
    body = "\n".join(lines) or "なし"
    return f"## その他のスレッド（{len(pairs)} 件）\n\n{body}"


def _context_pair(question, post, user_id):
    answer = {"datetime": post["datetime"], "user": user_id,
              "text": post["text"], "is_target_user": True}
    return {"role": "answerer", "source": "channel_context",
            "channel_name": post["channel_name"], "permalink": post["permalink"],
            "question": question, "answers": [answer]}


def _reject_unknown(keys, items, key, label):
    """判定ファイルのキーが collect の結果にあるか確かめる。"""
    # 書き間違いを無視すると、その他に回したはずのスレッドが黙って載るため止める
    unknown = set(keys) - {key(item) for item in items}
    if unknown:
        raise ValueError(f"collect の結果にない{label}です: {sorted(unknown)}")


def _context_pairs(data, entries):
    """判定ファイルが指したスレッド外の投稿を、collect の元データから組にする。"""
    # 索引の本文はデコード済みのため、写させると render で二重にデコードされる。元データから取る
    posts = {post_key(p): p for p in data["standalone_posts"]}
    _reject_unknown([e["post"] for e in entries], data["standalone_posts"], post_key, "投稿")
    return [_context_pair(e["question"], posts[e["post"]], data["user_id"]) for e in entries]


def _split(data, judgement):
    """載せる組と、「その他」に回すスレッドに分ける。"""
    pairs = data["qa_pairs"]
    other_keys = set(judgement.get("other_threads", []))
    _reject_unknown(other_keys, pairs, thread_key, "スレッド")
    shown = ([p for p in pairs if thread_key(p) not in other_keys]
             + _context_pairs(data, judgement.get("channel_context_pairs", [])))
    others = [p for p in pairs if thread_key(p) in other_keys]
    return shown, others


def render_markdown(data, judgement, period):
    """collect の出力と Claude の判定から、質問と回答の Markdown を作る。"""
    shown, others = _split(data, judgement)
    sections = [f"# 質問と回答: <@{data['user_id']}>（{period}）"]
    sections += [_render_section(title, [p for p in shown if p["role"] == role])
                 for role, title in SECTIONS]
    sections.append(_render_others(others))
    return "\n\n".join(sections) + "\n"
