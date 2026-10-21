# corpus/ — prlint の閾値と精度を測るためのコーパス

公開 OSS の日本語の PR 本文を集め、`prlint.py` を当てて、閾値の妥当性と検出の精度を測る。コーパス自体は成果物ではなく、検査スクリプトと [証拠表](../research/evidence-matrix.md) の「自前」の項目を裏付けるための実験基盤。結果は [reports/calibration.md](./reports/calibration.md) にある。

## 対象

日本語で PR を書く文化のある公開リポジトリ 10 個。25 個ほどの候補から、次の条件で選んだ。

- 最近マージされた PR の多くが、日本語で 150 字以上の本文を持つ
- 2022-11-01 より前と 2025-01-01 以降の両方に、そうした PR が十分にある

| リポジトリ | 分野 |
|---|---|
| EC-CUBE/ec-cube | EC サイト構築 |
| thinkingreed-inc/F-RevoCRM | CRM |
| sakura-editor/sakura | テキストエディタ |
| pixiv/charcoal | デザインシステム |
| zenn-dev/zenn-editor | 記事エディタ |
| VOICEVOX/voicevox | 音声合成アプリ |
| VOICEVOX/voicevox_engine | 音声合成エンジン |
| vivliostyle/vfm | Markdown 方言 |
| kmuto/review | 組版ツール |
| kufu/smarthr-ui | UI コンポーネント |

## 標本の取り方

- マージ済みの PR を、リポジトリごと・時期ごとに最大 25 本（新しい順）。特定のリポジトリのテンプレートに偏らないための上限
- 時期は 2 つ。**前期**は 2022-11-01 より前（ChatGPT の公開より前）、**後期**は 2025-01-01 以降。後期には AI が書いた本文が混ざりうるが、見分ける手段は無い
- 除外: bot の PR、日本語の文字が 60 字未満または 3 割未満の本文、HTML コメントを除いて 150 字未満の本文

条件は `sources.json` の `criteria` にも記録してある。

## ライセンスの扱い

| 置き場所 | 扱い | 理由 |
|---|---|---|
| `sources.json` | コミットする | URL とメタデータ（リポジトリ、番号、時期、作成日時）だけ |
| `bodies/` | コミットしない | PR 本文には著作権がある。`fetch` で各自が手元に取得する |
| `cache/` | コミットしない | Issue・PR のタイトルと、精度の判定に使った抜粋 |
| `reports/` | コミットする | 集計値だけ。原文は引用しない。精度の判定結果は URL・行・判定・誤りの種類だけ |

## 再現の手順

認証済みの `gh` が要る。

```
python3 corpus/corpus.py fetch     # sources.json の本文を bodies/ に取得
python3 corpus/corpus.py report    # reports/calibration.json を作る
python3 corpus/corpus.py sample    # 精度の判定に使う標本を cache/ に作る（seed は 0）
```

`collect` は対象を集め直して `sources.json` を上書きする。PR はその後も増えるので、同じ標本にはならない。

## 限界

- 10 リポジトリは無作為の標本ではない。日本語で PR を書く、比較的よく運営された OSS に偏っている
- 時期の差には、AI 以外の要因（リポジトリの成熟、テンプレートの変更、変更の規模）も混ざる
- 精度の判定は、人ではなく、prlint を書いていない AI のエージェントが行った
