#!/usr/bin/env python3
"""corpus.py — prlint.py の閾値と検出の傾向を、公開 OSS の日本語の PR 本文で測る。

使い方:
    python3 corpus/corpus.py collect   # 対象リポジトリから PR を集め、sources.json と bodies/ を作る
    python3 corpus/corpus.py fetch     # sources.json から bodies/ を作り直す（他の人が再現するとき）
    python3 corpus/corpus.py report    # bodies/ に prlint を当て、reports/ に集計を書く
    python3 corpus/corpus.py sample [SEED]  # 精度の判定に使う標本を cache/ に書く。判定済み（reports/*-labels.json）は除く

認証済みの gh が要る。bodies/ は著作権のある本文なのでコミットしない。reports/ には集計値だけを書く。
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from collections import Counter
from datetime import date
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "skills/natural-pr-issue-japanese/scripts"))
import prlint  # noqa: E402

# 選定条件は corpus/README.md
REPOS = [
    "EC-CUBE/ec-cube",
    "thinkingreed-inc/F-RevoCRM",
    "sakura-editor/sakura",
    "pixiv/charcoal",
    "zenn-dev/zenn-editor",
    "VOICEVOX/voicevox",
    "VOICEVOX/voicevox_engine",
    "vivliostyle/vfm",
    "kmuto/review",
    "kufu/smarthr-ui",
]
# pre は ChatGPT の公開（2022-11-30）より前、post は AI の執筆支援が広まった後
ERAS = {"pre": "created:<2022-11-01", "post": "created:>=2025-01-01"}
PER_REPO_ERA = 25
SAMPLE_PER_DETECTOR = 20
MIN_CHARS, MIN_JP_CHARS, MIN_JP_RATIO = 150, 60, 0.3
JP = re.compile(r"[ぁ-んァ-ヶ一-龠]")
# 敬体の文末を常体にしたときに減る字数のおおよそ（「しました」→「した」で 2 字など）
KEIGO_SAVINGS = [("ました", 2), ("ましょう", 2), ("ません", 1), ("ます", 1), ("でした", 0), ("でしょう", 0), ("です", 1)]


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def body_path(repo: str, number: int) -> Path:
    return ROOT / "bodies" / f"{repo.replace('/', '__')}__{number}.md"


def save_body(repo: str, number: int, body: str) -> None:
    path = body_path(repo, number)
    path.parent.mkdir(exist_ok=True)
    path.write_text(body or "", encoding="utf-8")


def is_japanese_body(body: str | None) -> bool:
    b = prlint.strip_comments(body or "")
    total, jp = len(re.sub(r"\s", "", b)), len(JP.findall(b))
    return total >= MIN_CHARS and jp >= MIN_JP_CHARS and jp / total >= MIN_JP_RATIO


def collect() -> None:
    prs = []
    for repo in REPOS:
        for era, query in ERAS.items():
            listed = json.loads(gh("pr", "list", "-R", repo, "--state", "merged", "--search", query, "--limit", "200",
                                   "--json", "number,url,createdAt,author,body"))
            picked = [p for p in listed
                      if not (p["author"].get("is_bot") or p["author"]["login"].endswith("[bot]")) and is_japanese_body(p["body"])]
            for p in picked[:PER_REPO_ERA]:
                save_body(repo, p["number"], p["body"])
                prs.append({"repo": repo, "number": p["number"], "url": p["url"], "era": era, "created_at": p["createdAt"]})
            print(f"{repo} {era}: {min(len(picked), PER_REPO_ERA)} / {len(listed)}", flush=True)
    sources = {
        "collected_at": date.today().isoformat(),
        "criteria": {"state": "merged", "eras": ERAS, "per_repo_era": PER_REPO_ERA, "min_chars": MIN_CHARS,
                     "min_jp_chars": MIN_JP_CHARS, "min_jp_ratio": MIN_JP_RATIO, "exclude": "bot の PR"},
        "prs": prs,
    }
    (ROOT / "sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def fetch() -> None:
    for s in json.loads((ROOT / "sources.json").read_text())["prs"]:
        save_body(s["repo"], s["number"], gh("pr", "view", s["url"], "--json", "body", "-q", ".body"))


def keigo_saving(sentence: str) -> int:
    s = sentence.rstrip("。！？!? 　)）」』*_`")
    # 依頼と問いかけは敬体のまま残す規則なので、減らせる字数に数えない
    if prlint.is_request(s) or s.endswith("か"):
        return 0
    return next((d for end, d in KEIGO_SAVINGS if s.endswith(end)), 0)


def measure(text: str) -> dict:
    findings, metrics = prlint.lint(text, all_detectors=True)
    blocks = prlint.parse(text)
    prose = prlint.prose(blocks)
    items = [b for b in prose if b.kind == "item"]
    paras = [b for b in prose if b.kind == "para"]
    sents = [s for b in items + paras for s in prlint.sentences(b.text)]
    return {
        "detectors": sorted({f.detector for f in findings}),
        "findings": len(findings),
        "bullet_sentences": [len(prlint.sentences(b.text)) for b in items],
        "keigo_bullets": sum(any(map(prlint.is_keigo, prlint.sentences(b.text))) for b in items),
        "bullets": len(items),
        "keigo_per_para": [sum(map(prlint.is_keigo, prlint.sentences(b.text))) for b in paras],
        "request_positions": [idx for idx, _, _ in prlint.request_positions(blocks)],
        "mid_list_refs": [ref for _, ref in prlint.mid_list_refs(blocks)],
        "keigo_sentences": sum(map(prlint.is_keigo, sents)),
        "keigo_savings": sum(keigo_saving(s) for s in sents if prlint.is_keigo(s)),
        "prose_chars": sum(len(s) for s in sents),
        "uses_details": "<details" in text,
        **metrics,
    }


def pct(xs: list[float], p: int) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, round(p / 100 * len(s) + 0.5) - 1))] if s else 0


def share(n: int, d: int) -> str:
    return f"{n / d:.1%}" if d else "-"


def resolve_title(ref: str, repo: str, cache: dict) -> str | None:
    if m := re.match(r"https://github\.com/([\w.-]+/[\w.-]+)/(?:pull|issues)/(\d+)", ref):
        target, num = m[1], m[2]
    elif "#" in ref:
        target, num = ref.split("#")
        target = target or repo
    elif ref.startswith("GH-"):
        target, num = repo, ref[3:]
    else:
        return None
    key = f"{target}#{num}"
    if key not in cache:
        try:
            cache[key] = gh("api", f"repos/{target}/issues/{num}", "--jq", ".title").strip()
        except subprocess.CalledProcessError:
            cache[key] = None
    return cache[key]


def sign_test(increased: list[bool], ties: list[bool]) -> dict:
    """リポジトリを対にした符号検定（両側）。同点は除く。"""
    n = sum(not t for t in ties)
    k = sum(i for i, t in zip(increased, ties) if not t)
    tail = sum(comb(n, j) for j in range(max(k, n - k), n + 1)) / 2**n
    return {"increased": k, "n": n, "p_two_sided": round(min(1.0, 2 * tail), 4)}


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    bullets = [x for r in rows for x in r["bullet_sentences"]]
    paras = [x for r in rows for x in r["keigo_per_para"]]
    reqs = [x for r in rows for x in r["request_positions"]]
    vis = [r["visible_chars"] for r in rows]
    det = Counter(d for r in rows for d in r["detectors"])
    keigo_rows = [r for r in rows if r["keigo_sentences"]]
    return {
        "prs": n,
        "detector_rate": {d: round(c / n, 3) for d, c in sorted(det.items())},
        "findings_per_pr": round(sum(r["findings"] for r in rows) / n, 2) if n else 0,
        "bullets": len(bullets),
        "bullet_sentences": {"p50": pct(bullets, 50), "p90": pct(bullets, 90), "p95": pct(bullets, 95), "p99": pct(bullets, 99),
                             "share_gt1": round(sum(x > 1 for x in bullets) / len(bullets), 3) if bullets else 0,
                             "share_gt2": round(sum(x > 2 for x in bullets) / len(bullets), 3) if bullets else 0,
                             "share_gt3": round(sum(x > 3 for x in bullets) / len(bullets), 3) if bullets else 0},
        "keigo_bullet_share": round(sum(r["keigo_bullets"] for r in rows) / max(1, sum(r["bullets"] for r in rows)), 3),
        "paragraphs": len(paras),
        "keigo_per_para": {"p90": pct(paras, 90), "p95": pct(paras, 95),
                           "share_gt2": round(sum(x > 2 for x in paras) / len(paras), 3) if paras else 0},
        "request_sections": len(reqs),
        "request_position": {"p50": pct(reqs, 50), "p90": pct(reqs, 90),
                             "share_gt2": round(sum(x > 2 for x in reqs) / len(reqs), 3) if reqs else 0},
        "visible_chars": {"p50": pct(vis, 50), "p90": pct(vis, 90)},
        "uses_details": round(sum(r["uses_details"] for r in rows) / n, 3) if n else 0,
        "keigo_savings": {
            "prs_with_keigo": len(keigo_rows),
            "per_keigo_sentence": round(sum(r["keigo_savings"] for r in keigo_rows) / max(1, sum(r["keigo_sentences"] for r in keigo_rows)), 2),
            "share_of_prose_chars": round(sum(r["keigo_savings"] for r in keigo_rows) / max(1, sum(r["prose_chars"] for r in keigo_rows)), 4),
        },
    }


def precision() -> dict:
    """reports/precision-*-labels.json（AI の判定者が付けた TP/FP）から、検出器ごとの精度を出す。"""
    out = {}
    for path in sorted((ROOT / "reports").glob("precision-*-labels.json")):
        labels = json.loads(path.read_text())
        name = path.name.removeprefix("precision-").removesuffix("-labels.json")
        out[name] = {}
        for det in sorted({x["detector"] for x in labels}):
            c = Counter(x["label"] for x in labels if x["detector"] == det)
            judged = c["TP"] + c["FP"]
            out[name][det] = {"TP": c["TP"], "FP": c["FP"], "UNSURE": c["UNSURE"],
                              "precision": round(c["TP"] / judged, 2) if judged else None}
    return out


def report() -> None:
    sources = json.loads((ROOT / "sources.json").read_text())
    rows = []
    for s in sources["prs"]:
        rows.append({**s, **measure(body_path(s["repo"], s["number"]).read_text(encoding="utf-8"))})

    cache_path = ROOT / "cache" / "titles.json"
    cache_path.parent.mkdir(exist_ok=True)
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    titles = [t for r in rows for ref in r["mid_list_refs"] if (t := resolve_title(ref, r["repo"], cache))]
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    title_lens = [len(t) for t in titles]

    by_repo = {}
    for repo in REPOS:
        v = {}
        for era in ERAS:
            rs = [r for r in rows if r["repo"] == repo and r["era"] == era]
            v[f"{era}_prs"] = len(rs)
            v[f"{era}_findings_per_pr"] = round(sum(r["findings"] for r in rs) / len(rs), 2) if rs else 0
            v[f"{era}_visible_p50"] = pct([r["visible_chars"] for r in rs], 50)
        by_repo[repo] = v

    result = {
        "collected_at": sources["collected_at"],
        "thresholds": {"MAX_BULLET_SENTENCES": prlint.MAX_BULLET_SENTENCES, "MAX_KEIGO_SENTENCES": prlint.MAX_KEIGO_SENTENCES,
                       "MAX_UNITS_BEFORE_REQUEST": prlint.MAX_UNITS_BEFORE_REQUEST},
        "all": summarize(rows),
        "by_era": {era: summarize([r for r in rows if r["era"] == era]) for era in ERAS},
        "by_repo": by_repo,
        "paired_sign_test": {k: sign_test([v[f"post_{k}"] > v[f"pre_{k}"] for v in by_repo.values()],
                                          [v[f"post_{k}"] == v[f"pre_{k}"] for v in by_repo.values()])
                             for k in ("findings_per_pr", "visible_p50")},
        "precision": precision(),
        "expanded_titles": {"mid_list_refs": sum(len(r["mid_list_refs"]) for r in rows), "resolved": len(title_lens),
                            "p50": pct(title_lens, 50), "p90": pct(title_lens, 90), "max": max(title_lens, default=0)},
    }
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "calibration.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


def sample(seed: int = 0) -> None:
    labeled = {(x["url"], x["line"], x["detector"]) for f in (ROOT / "reports").glob("*-labels.json") for x in json.loads(f.read_text())}
    by_detector: dict[str, list[dict]] = {}
    for s in json.loads((ROOT / "sources.json").read_text())["prs"]:
        text = body_path(s["repo"], s["number"]).read_text(encoding="utf-8")
        blocks = {b.line: b for b in prlint.parse(text)}
        lines = text.splitlines()
        for f in prlint.lint(text, all_detectors=True)[0]:
            if (s["url"], f.line, f.detector) in labeled:
                continue
            block = blocks.get(f.line)
            by_detector.setdefault(f.detector, []).append({
                "url": s["url"], "line": f.line, "detector": f.detector, "rule": f.rule, "message": f.message,
                "text": block.text if block else lines[f.line - 1],
            })
    rng = random.Random(seed)
    picked = [x for found in by_detector.values() for x in rng.sample(found, min(SAMPLE_PER_DETECTOR, len(found)))]
    out = ROOT / "cache" / f"review-sample-seed{seed}.jsonl"
    out.parent.mkdir(exist_ok=True)
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in picked), encoding="utf-8")
    print(f"{out}: {len(picked)} 件（{', '.join(f'{d} {min(SAMPLE_PER_DETECTOR, len(v))}' for d, v in sorted(by_detector.items()))}）")


if __name__ == "__main__":
    commands = {"collect": collect, "fetch": fetch, "report": report, "sample": sample}
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    commands[sys.argv[1]](*map(int, sys.argv[2:]))
