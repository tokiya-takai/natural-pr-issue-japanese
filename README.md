# natural-pr-issue-japanese

日本語の GitHub PR・Issue の本文を、読み手が本文だけで理解・判断でき、読む気になる量に書くための Claude Code・Codex スキルです。

AI に PR の本文を書かせると、次のような文面になりがちです。

- 参照先に説明を任せる（「#41 との違いを先に見てください」）
- ID だけを書き、中身を書かない（「REQ-012 を変える」）
- 敬体の長い一文に、依頼と比較と代わりの案を詰め込む
- 概要に問題を並べるだけで、どう直したかは詳細を読むまで分からない

このスキルは、こうした文面を避けるための規則と点検項目を AI エージェントに渡します。

## 規則

- 概要だけで、何をどういう方向で対応したかが分かるようにする
- 参照先の中身は、抜粋か要約で本文に書く
- `#N` を箇条書きの途中に置かない（GitHub が箇条書きの中の参照をタイトル付きで展開し、文の途中に長いタイトルが挟まるため）
- 同じものは同じ言葉で呼び、用語は初出で説明する
- 一つの箇条に話題は一つ、2 文までを目安に
- 頼みごとを先に書く
- 地の文は敬体、見出し・箇条書き・表は常体で書き、内容が続くときは箇条書きか表に出す
- 判断に使わないことは書かないか、`<details>` で畳む

規則ごとの例と点検項目は [SKILL.md](skills/natural-pr-issue-japanese/SKILL.md) にあります。

## 検査スクリプト

`skills/natural-pr-issue-japanese/scripts/prlint.py` は、本文から規則に反する疑いのある箇所を出します。Python の標準ライブラリだけで動きます（3.13 で確認）。

```
python3 skills/natural-pr-issue-japanese/scripts/prlint.py BODY.md
gh pr view 12 --json body -q .body | python3 skills/natural-pr-issue-japanese/scripts/prlint.py -
```

| 検出器 | 規則 | 見ているもの | 精度 |
|---|---|---|---|
| `summary_problem_only` | 1 | 概要の番号付きの項目に、対応の方向が書かれていない | 未測定 |
| `ref_in_list` | 3 | 箇条書きの途中に `#N` や PR・Issue の URL がある | 80% |
| `preview_heading_mismatch` | 4 | 概要の項目と、詳細の見出しの文言が違う | 未測定 |
| `long_bullet` | 5 | 3 文以上ある箇条 | 95% |
| `request_late` | 6 | 節の頭から 3 つ目以降に、頼みごとがある | 80%（5 件） |
| `keigo_bullet` | 7 | 敬体の箇条 | 100% |
| `long_keigo_prose` | 7 | 問いかけ・依頼を除き、敬体の文が 3 文以上ある段落 | 95% |
| `details_syntax` | 8 | `<details>` の中の空行が足りない | 未測定 |
| `bare_id`（`--all`） | 2 | ID や `#N` の中身の説明が、本文のどこにも無い | 30% |
| `undefined_term`（`--all`） | 4 | 略語の初出に説明が無い | 0%（修正前） |

精度は、公開 OSS の PR で検出した箇所を、検出器ごとに最大 20 件ずつ AI の判定者が判定した値です（判定に使っていない標本で測った値。未測定はコーパスで検出が無かったもの）。精度の低い 2 つは、`--all` を付けたときだけ出します。

ほかに、`<details>` で畳んだ部分を除いた「見えている字数」も出します。検出は疑いの提示で、直すかどうかは文脈で判断します。

閾値と精度は、公開 OSS の日本語の PR 479 本で測りました（[corpus/](corpus/README.md)）。

回帰テストは `python3 -m unittest discover tests` で実行できます。

## 根拠

規則ごとに、外部研究がどこまで支えているかを [証拠表](research/evidence-matrix.md) にまとめました。判定には「直接」「間接」「規範」「未確認」「反証的」などのラベルを付け、根拠が弱い規則や反証のある規則もそのまま載せています。文献の書誌と確認の方法は [文献レビュー](research/literature-review.md) にあります。

PR・Issue の本文そのものを対象にした実験はほとんど無く、大半は一般の文章・学習教材・web ページでの研究を当てはめた間接的な根拠です。人の読み手を集めた効果の測定は行っていません。

## インストール

### Claude Code

```
/plugin marketplace add tokiya-takai/natural-pr-issue-japanese
/plugin install natural-pr-issue-japanese@natural-pr-issue-japanese
```

### Codex

```
codex plugin marketplace add tokiya-takai/natural-pr-issue-japanese
codex plugin add natural-pr-issue-japanese@natural-pr-issue-japanese
```

インストール後、新しいセッションでスキルを使えます。

## 使い方

PR や Issue の本文を書くとき（`gh pr create` などの前）に、エージェントがこのスキルを選んで使います。明示的に呼ぶときは次のとおりです。

### Claude Code

```
/natural-pr-issue-japanese:natural-pr-issue-japanese <PR の URL> の本文を書き直して
```

### Codex

```
$natural-pr-issue-japanese:natural-pr-issue-japanese <PR の URL> の本文を書き直して
```

- [natural-japanese](https://github.com/coji/natural-japanese) が入っていれば、仕上げにそれも通す（任意）
- プロジェクト固有の約束（PR テンプレートの章、CI が検査する書式など）は、使うエージェント向けの指示ファイルに書けばそちらに従う（Claude Code は `CLAUDE.md`、Codex は `AGENTS.md`）

## ライセンス

MIT
