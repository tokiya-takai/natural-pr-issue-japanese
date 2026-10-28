#!/usr/bin/env python3
"""prlint.py — PR・Issue の本文（Markdown）から、SKILL.md の規則に反する疑いのある箇所を出す。

使い方:
    python3 prlint.py BODY.md
    python3 prlint.py BODY.md --json
    python3 prlint.py BODY.md --all      # 精度の低い検出器（bare_id, undefined_term）も出す
    gh pr view 12 --json body -q .body | python3 prlint.py -

検出は疑いの提示で、直すかどうかは文脈で判断する。規則の番号は SKILL.md の「書き方」の番号、
根拠は research/evidence-matrix.md。標準ライブラリだけで動く。
終了コードは検出件数に関わらず 0、入力エラーのときだけ 1。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from itertools import takewhile

# 閾値はコーパスで校正する前の初期値（research/evidence-matrix.md の「自前（予定）」）
MAX_BULLET_SENTENCES = 2
MAX_KEIGO_SENTENCES = 2
MAX_UNITS_BEFORE_REQUEST = 2

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
CHECKBOX = re.compile(r"^\[[ xX]\]\s")
NUMBERED = re.compile(r"^(\d+)[.)]\s*(.*)$")
SUMMARY = re.compile(r"^(概要|サマリー?|要約|summary|overview)$", re.I)
REF_LINE = re.compile(r"^参照\s*[:：]")
# 日本語の文字を語の一部とみなさないよう ASCII モードで書く
REF = re.compile(
    r"https://github\.com/[\w.-]+/[\w.-]+/(?:pull|issues|discussions)/\d+[\w/#?=&.-]*"
    r"|(?<![\w/#&])(?:[\w.-]+/[\w.-]+)?#\d+\b"
    r"|\bGH-\d+\b",
    re.ASCII,
)
ID = re.compile(r"(?<![\w-])([A-Z][A-Z0-9]{0,5}(?:-[A-Z0-9]+)*-\d+)(?![\w-])", re.ASCII)
ID_PREFIX_ALLOW = {"UTF", "SHA", "ISO", "AES", "RSA", "RFC", "COVID", "MD"}
ID_ALLOW = {"P-256", "P-384", "P-521"}  # 楕円曲線の名前
ACRONYM = re.compile(r"(?<![\w.-])([A-Z]{2,6})(?![\w-])", re.ASCII)
COMMON_ACRONYMS = {
    "PR", "CI", "CD", "API", "URL", "UI", "UX", "DB", "CSV", "JSON", "YAML", "XML", "HTML", "CSS",
    "JS", "TS", "HTTP", "HTTPS", "SQL", "OS", "ID", "PDF", "AWS", "GCP", "GPU", "CPU", "SDK", "CLI",
    "IDE", "OK", "NG", "LGTM", "WIP", "README", "TODO", "FAQ", "MIT", "KB", "MB", "GB", "TB", "AI",
    "LLM", "QA", "USB", "SSH", "SSL", "TLS", "DNS", "IP", "TCP", "UDP", "VM", "RAM", "SSD", "PNG",
    "JPG", "JPEG", "SVG", "GIF", "MP", "UTF", "PC",
}
PARTICLE = re.compile(r"\s*(を|は|が|に|の|と|で|も|へ|から|まで|より|や)")
# 「#N で〜を直した」「#N と同様に〜」のように、続く節がその番号の中身を語っている
INLINE_EXPLAIN = re.compile(r"\s*(で|を受けて|と同様に|と同じく|に続いて)(?=[^。！？]{10,})")
KEIGO_END = re.compile(r"(です|ます|ました|ません|でした|ください|ましょう|でしょう|ますか|ですか)$")
REQUEST = re.compile(r"(ご?確認|ご?判断|ご?意見|ご?検討|ご?相談|ご?指摘|レビュー|見て|教えて|決めて|選んで|承認)[^。]{0,12}?(ください|お願い|いただきたい|いただけ)")
# 締めのあいさつと、頼みごとではない注意書き・手順
NOT_REQUEST = re.compile(r"^(@\S+\s*)*((レビュー|ご?確認)(を|の程)?)?(よろしく)?お願い(します|いたします|致します)[。！!]*$|ご?留意|ご?注意|参照して|場合は")
ACTION = re.compile(r"(した|します|にする|ようにする|変える|変えた|直す|修正|変更|追加|削除|導入|→|⇒)")
QUESTION_END = re.compile(r"(か|？|\?)$")


@dataclass
class Block:
    kind: str  # heading / item / para
    line: int
    text: str
    level: int = 0
    indent: int = 0
    numbered: str | None = None
    checkbox: bool = False


@dataclass
class Finding:
    line: int
    rule: int
    detector: str
    message: str
    excerpt: str


def strip_comments(text: str) -> str:
    # bot が自動生成した要約（CodeRabbit など）は書き手の文章ではないので、検査から外す
    text = re.sub(r"<!--\s*This is an auto-generated comment.*?<!--\s*end of auto-generated comment.*?-->",
                  lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S | re.I)
    return re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)


def parse(text: str) -> list[Block]:
    blocks: list[Block] = []
    cur: Block | None = None
    in_code = False
    for no, raw in enumerate(strip_comments(text).splitlines(), 1):
        s = raw.rstrip()
        if s.lstrip().startswith(("```", "~~~")):
            in_code, cur = not in_code, None
            continue
        if in_code or s.strip() in ("", ">") or s.lstrip().startswith("<"):
            cur = None
            continue
        if m := HEADING.match(s):
            blocks.append(Block("heading", no, m[2], level=len(m[1])))
            cur = None
        elif m := ITEM.match(s):
            num = m[2].rstrip(".)") if m[2][0].isdigit() else None
            cur = Block("item", no, m[3], indent=len(m[1]), numbered=num, checkbox=bool(CHECKBOX.match(m[3])))
            blocks.append(cur)
        elif cur is not None:
            cur.text += s.strip()
        else:
            cur = Block("para", no, s.strip())
            blocks.append(cur)
    return blocks


def mask_code(t: str) -> str:
    return re.sub(r"`[^`]*`", lambda m: "＿" * len(m.group(0)), t)


def mask_all(t: str) -> str:
    return re.sub(r"https?://\S+", lambda m: "＿" * len(m.group(0)), mask_code(t))


def sentences(t: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[。！？!?])", mask_all(t)) if s.strip()]


def is_keigo(sentence: str) -> bool:
    return bool(KEIGO_END.search(sentence.rstrip("。！？!? 　)）」』*_`")))


def is_request(sentence: str) -> bool:
    return bool(REQUEST.search(sentence)) and not NOT_REQUEST.search(sentence.strip())


def inside_paren(t: str, pos: int) -> bool:
    head = t[:pos]
    return sum(head.count(c) for c in "（(") > sum(head.count(c) for c in "）)")


def excerpt(t: str, n: int = 60) -> str:
    return t if len(t) <= n else t[:n] + "…"


def prose(blocks: list[Block]) -> list[Block]:
    """文体の検出の対象。CI が書式を見るチェックボックス行と参照行は除く。"""
    return [b for b in blocks if not b.checkbox and not (b.kind == "para" and REF_LINE.match(b.text))]


def summary_region(blocks: list[Block]) -> list[Block]:
    for i, b in enumerate(blocks):
        if b.kind == "heading" and SUMMARY.match(b.text.strip()):
            end = next((j for j in range(i + 1, len(blocks)) if blocks[j].kind == "heading" and blocks[j].level <= b.level), len(blocks))
            return blocks[i + 1 : end]
    return []


def d_summary_direction(region: list[Block]) -> list[Finding]:
    items = [b for b in takewhile(lambda b: b.kind != "heading", region) if b.kind == "item"]
    out = []
    for i, b in enumerate(items):
        # 失敗例はどれも「次の 2 件」のような番号付きの列挙だったので、番号付きの項目だけを見る
        if b.indent or b.checkbox or not b.numbered:
            continue
        block = b.text + "".join(c.text for c in takewhile(lambda c: c.indent > 0, items[i + 1 :]))
        if not ACTION.search(block):
            out.append(Finding(b.line, 1, "summary_problem_only",
                               "概要の項目に対応の方向が無い。どう直したか（したいか）を 1〜2 行添える", excerpt(b.text)))
    return out


def d_preview_heading(region: list[Block]) -> list[Finding]:
    def norm(s: str) -> str:
        return re.sub(r"[\s*_`。、．.]", "", s)

    pre = {b.numbered: b for b in takewhile(lambda b: b.kind != "heading", region) if b.kind == "item" and b.numbered and not b.indent}
    heads = {m[1]: (b, m[2]) for b in region if b.kind == "heading" and (m := NUMBERED.match(b.text))}
    if not pre or not heads:
        return []
    out = []
    for n, it in pre.items():
        if n not in heads:
            out.append(Finding(it.line, 4, "preview_heading_mismatch", f"概要の {n}. に対応する詳細の見出しが無い", excerpt(it.text)))
        elif norm(heads[n][1]) != norm(it.text):
            h, ht = heads[n]
            out.append(Finding(h.line, 4, "preview_heading_mismatch",
                               f"概要「{n}. {it.text}」と見出し「{n}. {ht}」の文言が違う。同じ文言に揃える", excerpt(h.text)))
    for n, (h, _) in heads.items():
        if n not in pre:
            out.append(Finding(h.line, 4, "preview_heading_mismatch", f"見出し {n}. に対応する概要の項目が無い", excerpt(h.text)))
    return out


def is_bare(t: str, start: int, end: int) -> bool:
    """「REQ-012 を変える」のように、中身の説明なしに助詞が直接続く使い方か。"""
    if inside_paren(t, start) or INLINE_EXPLAIN.match(t[end:]):
        return False
    p = PARTICLE.match(t[end:])
    if not p:
        return False
    rest = t[end + p.end() :]
    if rest[:1] in tuple("「『（("):
        return False
    if p[1] in ("は", "が") and "「" in re.split(r"[。！？]", rest, maxsplit=1)[0]:
        return False
    # 「配布版での登録を禁じていた FR-018 を」のように、前の修飾節で中身を説明している
    head = re.split(r"[、。「（(:：]", t[:start])[-1].rstrip()
    return not (len(head) >= 8 and head[-1:] in tuple("たるい"))


def d_bare_id(blocks: list[Block]) -> list[Finding]:
    occurrences = []
    for b in prose(blocks):
        t = mask_code(b.text)
        occurrences += [(b, m.start(1), m.end(1), m[1], t) for m in ID.finditer(t)
                        if m[1].split("-")[0] not in ID_PREFIX_ALLOW and m[1] not in ID_ALLOW]
        occurrences += [(b, m.start(), m.end(), m[0], t) for m in REF.finditer(t)]
    # どこか 1 か所で説明していれば、ほかの箇所は同じ呼び名で使ってよい
    explained = {key for _, start, end, key, t in occurrences if not is_bare(t, start, end)}
    out, seen = [], set()
    for b, _, _, key, _ in occurrences:
        # 箇条書きの中の参照は d_ref_in_list が見る（説明済みかどうかの判定にだけ使う）
        if key in explained or key in seen or (b.kind == "item" and key.startswith(("#", "http", "GH-"))):
            continue
        seen.add(key)
        out.append(Finding(b.line, 2, "bare_id",
                           f"`{key}` の中身の説明がどこにも無い。この文脈で必要な中身を括弧か引用で添える", excerpt(b.text)))
    return out


def mid_list_refs(blocks: list[Block]) -> list[tuple[Block, str]]:
    """箇条書きの項目の途中にある参照（後ろに文が続くもの）を、項目ごとに最初の 1 つ返す。"""
    out = []
    for b in blocks:
        if b.kind != "item" or b.checkbox:
            continue
        t = mask_code(b.text)
        for m in REF.finditer(t):
            # 項目の頭の「#123:」というラベルは、後ろの文を分断しない
            if not t[: m.start()].strip(" *_") and re.match(r"\s*[:：]", t[m.end() :]):
                continue
            rest = REF.sub("", t[m.end() :])
            # 項目末尾の括弧の中の参照（「（#123 で報告）」）は、括弧の外の文を分断しない
            if inside_paren(t, m.start()):
                rest = re.sub(r"^[^）)]*[）)]", "", rest)
            rest = re.sub(r"[（(][^）)]*[）)]", "", rest)
            if re.sub(r"[\s、。,.:：;；・/*_]+", "", rest):
                out.append((b, m[0]))
                break
    return out


def d_ref_in_list(blocks: list[Block]) -> list[Finding]:
    return [Finding(b.line, 3, "ref_in_list",
                    f"箇条書きの中の `{ref}` の後ろに文が続いている。GitHub がタイトル付きで展開し、文が分断される。内容で呼び、番号は `参照:` 行へ",
                    excerpt(b.text))
            for b, ref in mid_list_refs(blocks)]


def d_undefined_term(blocks: list[Block]) -> list[Finding]:
    seen: set[str] = set()
    out = []
    for b in prose(blocks):
        if b.kind == "heading":
            continue
        t = mask_all(b.text)
        for m in ACRONYM.finditer(t):
            w = m[1]
            if w in COMMON_ACRONYMS or w in seen:
                continue
            seen.add(w)
            if t[m.end() :].lstrip()[:1] in tuple("（(=＝:：") or inside_paren(t, m.start()):
                continue
            out.append(Finding(b.line, 4, "undefined_term", f"略語 `{w}` の初出に説明が無い（読み手が知っている語なら残してよい）", excerpt(b.text)))
    return out


def d_long_bullet(blocks: list[Block]) -> list[Finding]:
    return [Finding(b.line, 5, "long_bullet", f"箇条の中に {n} 文ある（目安は {MAX_BULLET_SENTENCES} 文まで）。分けるか入れ子にする", excerpt(b.text))
            for b in prose(blocks) if b.kind == "item" and (n := len(sentences(b.text))) > MAX_BULLET_SENTENCES]


def d_keigo_bullet(blocks: list[Block]) -> list[Finding]:
    return [Finding(b.line, 7, "keigo_bullet", "敬体の箇条がある。箇条書きは常体にする", excerpt(b.text))
            for b in prose(blocks) if b.kind == "item" and any(is_keigo(s) for s in sentences(b.text))]


def d_long_keigo_prose(blocks: list[Block]) -> list[Finding]:
    return [Finding(b.line, 7, "long_keigo_prose",
                    f"問いかけ・依頼を除いて敬体の文が {k} 文ある段落。内容は箇条書きか表に出し、常体で書く", excerpt(b.text))
            for b in prose(blocks) if b.kind == "para" and (k := sum(is_keigo(s) and not is_request(s) and not s.rstrip("。 ").endswith("か")
                                                                     for s in sentences(b.text))) > MAX_KEIGO_SENTENCES]


def request_positions(blocks: list[Block]) -> list[tuple[int, int, str]]:
    """節ごとに、最初の頼みごとが節の何番目の文・箇条にあるかを (番号, 行, 文) で返す。"""
    sections: list[tuple[Block | None, list[Block]]] = [(None, [])]
    for b in blocks:
        if b.kind == "heading":
            sections.append((b, []))
        else:
            sections[-1][1].append(b)
    out = []
    for head, body in sections:
        # 見出しが問いになっている節と、大枠を先に書く概要の節は対象外
        if head is not None and (QUESTION_END.search(head.text.rstrip()) or SUMMARY.match(head.text.strip())):
            continue
        units = []
        for b in body:
            units += [(b.line, b.text)] if b.kind == "item" else [(b.line, s) for s in sentences(b.text)]
        idx = next((i for i, (_, t) in enumerate(units) if is_request(t)), None)
        if idx is not None:
            out.append((idx, *units[idx]))
    return out


def d_request_late(blocks: list[Block]) -> list[Finding]:
    return [Finding(line, 6, "request_late",
                    f"頼みごとの前に {idx} 文・箇条ある。何を決めてほしいかを見出しか冒頭に書く（不利な判断を伝えるときは理由が先でよい）",
                    excerpt(t))
            for idx, line, t in request_positions(blocks) if idx > MAX_UNITS_BEFORE_REQUEST]


def d_details_syntax(text: str) -> list[Finding]:
    lines = strip_comments(text).splitlines()
    out, in_code = [], False
    for i, raw in enumerate(lines):
        if raw.lstrip().startswith(("```", "~~~")):
            in_code = not in_code
        if in_code:
            continue
        if "</summary>" in raw and i + 1 < len(lines) and lines[i + 1].strip():
            out.append(Finding(i + 1, 8, "details_syntax", "`</summary>` の次の行が空いていない。空行が無いと中の Markdown が描画されない", excerpt(raw.strip())))
        if raw.strip() == "</details>" and i > 0 and lines[i - 1].strip() and "<details" not in lines[i - 1]:
            out.append(Finding(i + 1, 8, "details_syntax", "`</details>` の前の行が空いていない", excerpt(raw.strip())))
    return out


def metrics(text: str) -> dict:
    visible = total = depth = 0
    for raw in strip_comments(text).splitlines():
        n = len(re.sub(r"\s", "", re.sub(r"<[^>]+>", "", raw)))
        total += n
        opens, closes = raw.count("<details"), raw.count("</details>")
        if depth == 0:
            if opens:
                m = re.search(r"<summary>(.*?)</summary>", raw)
                visible += len(re.sub(r"\s", "", m[1])) if m else 0
            else:
                visible += n
        depth = max(0, depth + opens - closes)
    return {"visible_chars": visible, "total_chars": total}


def lint(text: str, all_detectors: bool = False) -> tuple[list[Finding], dict]:
    """all_detectors が偽なら、コーパスで精度の低かった bare_id と undefined_term を出さない。"""
    blocks = parse(text)
    region = summary_region(blocks)
    findings = (
        d_summary_direction(region) + (d_bare_id(blocks) if all_detectors else []) + d_ref_in_list(blocks) + d_preview_heading(region)
        + (d_undefined_term(blocks) if all_detectors else []) + d_long_bullet(blocks) + d_request_late(blocks) + d_keigo_bullet(blocks)
        + d_long_keigo_prose(blocks) + d_details_syntax(text)
    )
    return sorted(findings, key=lambda f: (f.line, f.rule)), metrics(text)


def main(argv: list[str]) -> int:
    args = [a for a in argv if a not in ("--json", "--all")]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 1
    try:
        text = sys.stdin.read() if args[0] == "-" else open(args[0], encoding="utf-8").read()
    except OSError as e:
        print(f"読み込めません: {e}", file=sys.stderr)
        return 1
    findings, m = lint(text, all_detectors="--all" in argv)
    if "--json" in argv:
        print(json.dumps({"file": args[0], "findings": [asdict(f) for f in findings], "metrics": m}, ensure_ascii=False, indent=2))
        return 0
    print(f"=== prlint: {args[0]} ===")
    print(f"検出件数: {len(findings)}")
    for f in findings:
        print(f"\nL{f.line} [規則 {f.rule} / {f.detector}] {f.message}\n    該当: {f.excerpt}")
    print(f"\n見えている字数: {m['visible_chars']}（全体 {m['total_chars']}。<details> で畳んだ部分を除く）")
    print("※ 検出は疑いの提示。直すかどうかは文脈で判断する")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
