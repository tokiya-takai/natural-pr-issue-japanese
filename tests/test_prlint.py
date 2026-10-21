"""prlint.py の回帰テスト。`python3 -m unittest discover tests` で実行する。"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "skills/natural-pr-issue-japanese/scripts"))
import prlint  # noqa: E402


def detectors(text: str, all_detectors: bool = True) -> set[str]:
    return {f.detector for f in prlint.lint(text, all_detectors)[0]}


# SKILL.md の「例」の書き直す前と後
BAD_REVIEW = """\
- **PR #41 との方針の違いを先に見てください。** PR #41 は REQ-012「試用環境では行わない」を維持してサンプルリセットを止める方向、この PR は REQ-012 を変えて試用環境にもサンプルデータを入れる方向（DEC-07）。どちらにするかはレビュワーの判断で、PR #41 の方針を採るならこの PR から DEC-07 と `seed.ts` / `deploy.yml` の変更を落として型修正だけの PR にする
"""

GOOD_REVIEW = """\
### 1. 試用環境にサンプルデータを入れるか

試用環境でのサンプルデータの扱いが、この PR と develop に入っている修正で逆方向です。どちらを採るかご判断ください。

- 背景: REQ-012 は「サンプルデータの投入は開発環境だけで行い、試用環境では行わない」。一方、前回のレビューで「営業のデモは試用環境で行う」と決まり、試用環境にもサンプルの案件が要る
- **develop の修正の方向**: REQ-012 はそのまま。試用環境にはサンプルデータを入れず、サンプルリセット（夜間にデータを消し、サンプルから作り直す処理）も止めるため、試用環境ではサンプルの案件を見せられない
- **この PR の方向**: REQ-012 を「試用環境でもサンプルデータを投入する」に変え、デプロイ時に投入する（DEC-07）
- develop の修正の方向を採る場合: この PR からサンプル投入の変更（DEC-07、`seed.ts`、`deploy.yml`）を外し、型の修正だけ残す

参照: #41（develop の修正）、#35（「営業のデモは試用環境で行う」と決めたレビュー）
"""

BAD_SUMMARY = """\
## 概要

次の 2 件を対応しました。

1. 試用環境にサンプルの案件が入らない
2. 型エラーが 30 件残っている

### 1. 試用環境にもサンプルデータを投入する

- 原因: REQ-012（サンプルデータの投入は開発環境だけ）があった
"""

GOOD_SUMMARY = """\
## 概要

前回のレビューで持ち越した 2 件を、次の方向で対応しました。

1. 試用環境でサンプルの案件が出ない
   - デプロイ時にサンプルデータを投入するようにした
2. 型エラーが 30 件残っている
   - 型の書き方を直した

### 1. 試用環境でサンプルの案件が出ない

- 原因: REQ-012（サンプルデータの投入は開発環境だけ）があった

### 2. 型エラーが 30 件残っている

- 対応: any を具体的な型に置き換えた
"""


class PrlintTest(unittest.TestCase):
    def test_bad_review(self):
        self.assertLessEqual({"ref_in_list", "long_bullet", "keigo_bullet"}, detectors(BAD_REVIEW))

    def test_good_review(self):
        self.assertEqual(set(), detectors(GOOD_REVIEW))

    def test_bad_summary(self):
        found = [f.detector for f in prlint.lint(BAD_SUMMARY)[0]]
        self.assertEqual(2, found.count("summary_problem_only"))
        self.assertEqual(2, found.count("preview_heading_mismatch"))  # 1. の文言違いと 2. の見出し欠け

    def test_good_summary(self):
        self.assertEqual(set(), detectors(GOOD_SUMMARY))

    def test_bare_id(self):
        self.assertIn("bare_id", detectors("REQ-012 を変える。"))
        self.assertIn("bare_id", detectors("#41 との違いを先に見てください。"))
        self.assertNotIn("bare_id", detectors("REQ-012（サンプルデータの投入は開発環境だけ）を変える。"))
        self.assertNotIn("bare_id", detectors("REQ-012 は「開発環境だけで投入する」と定めている。"))
        self.assertNotIn("bare_id", detectors("配布版での登録を禁じていた FR-018 を変えた。"))
        self.assertNotIn("bare_id", detectors("#120 で入れた並べ替えの処理を、一覧画面にも使った。"))
        self.assertNotIn("bare_id", detectors("#120 を受けて直した。\n\n- #120（並べ替えの不具合）\n"))
        self.assertNotIn("bare_id", detectors("署名には P-256 を使う。"))
        self.assertNotIn("bare_id", detectors("D-008 と D-017 は未実装。\n\n- D-008: 値を再生に反映する\n- D-017: 信号に反映する\n"))

    def test_ref_at_end_of_item_is_fine(self):
        self.assertNotIn("ref_in_list", detectors("- 取り込んだ PR: #6、#9、#10\n"))
        self.assertIn("ref_in_list", detectors("- #9 の方針と逆にした\n"))
        self.assertNotIn("ref_in_list", detectors("- 並べ替えが崩れる不具合を直した（#120 で報告）\n"))
        self.assertNotIn("ref_in_list", detectors("- #120: 並べ替えが崩れる不具合を直した\n"))

    def test_checkbox_lines_are_left_alone(self):
        self.assertEqual(set(), detectors("- [x] OK: FR-018 を満たす。確認しました。開発環境で見ました。\n"))

    def test_details_syntax(self):
        self.assertIn("details_syntax", detectors("<details><summary>その他</summary>\n- a\n</details>\n"))
        self.assertNotIn("details_syntax", detectors("<details><summary>その他</summary>\n\n- a\n\n</details>\n"))

    def test_request_late(self):
        text = "### 依頼\n\n背景はこうだ。経緯はこうだ。\n\n- a\n- b\n\nご判断ください。\n"
        self.assertIn("request_late", detectors(text))
        self.assertNotIn("request_late", detectors("### 依頼\n\nご判断ください。\n\n- a\n- b\n- c\n"))
        closing = "### 変更\n\nA を直した。B も直した。C も直した。\n\nレビューよろしくお願いします。\n"
        self.assertNotIn("request_late", detectors(closing))

    def test_request_after_summary_is_fine(self):
        text = "## 概要\n\n2 件を対応しました。\n\n1. A が出ない\n   - B にした\n2. C が残る\n   - D を直した\n\nどちらを採るかご判断ください。\n"
        self.assertNotIn("request_late", detectors(text))

    def test_long_keigo_prose(self):
        self.assertIn("long_keigo_prose", detectors("修正しました。確認しました。問題ありません。\n"))
        self.assertNotIn("long_keigo_prose", detectors("修正しました。確認しました。ご確認ください。\n"))

    def test_bot_summary_is_skipped(self):
        bot = "<!-- This is an auto-generated comment: release notes by coderabbit.ai -->\n- 修正しました。\n<!-- end of auto-generated comment: release notes by coderabbit.ai -->\n"
        self.assertEqual(set(), detectors(bot))

    def test_undefined_term(self):
        self.assertIn("undefined_term", detectors("IDD で進めた。\n"))
        self.assertNotIn("undefined_term", detectors("IDD（実装しながら仕様を固める進め方）で進めた。\n"))

    def test_low_precision_detectors_are_opt_in(self):
        self.assertEqual(set(), detectors("IDD で進めた。REQ-012 を変える。\n", all_detectors=False))

    def test_visible_chars_exclude_details(self):
        m = prlint.lint("見える\n\n<details><summary>畳む</summary>\n\n隠れている文\n\n</details>\n")[1]
        self.assertEqual(5, m["visible_chars"])  # 「見える」3 字 + summary の「畳む」2 字
        self.assertLess(m["visible_chars"], m["total_chars"])


if __name__ == "__main__":
    unittest.main()
