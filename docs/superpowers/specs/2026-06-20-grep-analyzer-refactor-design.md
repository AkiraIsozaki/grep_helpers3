# grep_analyzer コード健全性リファクタリング 設計（診断ファースト）

- 日付: 2026-06-20
- 対象: `src/grep_analyzer/`（57ファイル / 約5,400 LOC）
- 目的: コードベース全体の健全性向上。**名前設計**を最優先軸とし、一般的な保守性向上・シンプル化も含める。

## 背景と狙い

`grep_analyzer` は grep/ripgrep 出力を起点にシンボルを追跡・分類する解析ツール。
すでにモジュール分割は進んでいる（最大 `fixedpoint/_scan.py` で 422 行）が、ユーザーの観察として
「プログラム中に長めのコメントが書かれていることがままあり、設計（特に名前）がうまく
いっていないサインではないか」という懸念がある。

本作業の方針:

- 長いコメントは **「名前・構造で語れていない代償」のサイン**として扱う。
  コメント削除を目的化せず、**名前付け・関数分割でコードを自明化し、結果としてコメントが減る**ことを狙う。
- 正当な WHY/契約（非自明な判断、不変条件、降格契約など）を説明するコメントは**残すべき価値**として区別する。
  例: `fixedpoint/_seed.py` の「seed_hits は direct パスがファイル単位でまとめて構築するため
  同一ファイルが連続する」は正当な WHY。
- メモリ記載の方針を順守する: コメントは保守的にトリム / コメントは体言止めを避け述語のある文 /
  main 直コミット（feature branch なし） / pytest は wheelhouse の `.venv` を有効化して実行（baseline 638 passed）。

## フェーズ構成

**フェーズ1（read-only 診断）→ フェーズ2（TDD で選択的に実装）** の二段構え。
コードを変更するのはフェーズ2、診断レポートにユーザーが合意した後のみ。

## フェーズ1: 診断

### スキャン方法

パッケージ単位で並列に監査を行い、横断的に所見を集約する。区分け:

- **top-level**: `cli`, `pipeline`, `dispatch`, `walk`, `ripgrep`, `ingest`, `resume`,
  `output_writer`, `model`, `chase`, `decode_cache`, `budget`, `spill`, `provenance`,
  `tsv`, `encoding`, `automaton`, `stoplist`, `classify`, `progress`, `diagnostics`,
  `embed_preprocess`, `proc_preprocess`
- **fixedpoint/**: `_scan`, `_lockstep`, `_seed`, `_ingest`, `_state`, `_finalize`,
  `_options`, `_budget_control`, `_encmemo`
- **classifiers/**: 各言語 chaser（`python_chaser`, `java_chaser`, `c_chaser`,
  `sql_chaser`, `perl_chaser`, `shell_chaser`, `groovy_chaser`, `javascript_chaser`,
  `typescript_chaser`）+ `base`, `regex_classifier`, `ts_classifier`
- **snippet/** + **patterns/**: `_heuristic`, `_clamp`, `_ts`, `_sanitize_line` /
  `symbol_extraction`, `snippet_boundaries`, `literal_masking`

### 診断カテゴリ

各所見は次を持つ: **場所** `file:line` / **問題** / **重大度**（high/medium/low） /
**労力**（S/M/L） / **改善案** / **before→after スケッチ**。

1. **命名（最優先）** — 自明でない関数/変数/モジュール名、略語、誤解を招く名前、
   モジュール間の一貫性欠如、ドメイン語彙との不一致。
2. **構造・責務** — 1関数が複数責務を持つ、長すぎる関数、曖昧なモジュール境界、
   不適切な依存方向。
3. **シンプル化・重複** — 重複ロジック、過剰な分岐、不要な間接、YAGNI 違反、
   デッドコード。
4. **コメント臭** — 「名前/構造で語れていないための長コメント」を特定し、
   命名・分割での自明化案に変換する。正当な WHY/契約コメントは「**残す**」と
   明記して区別する。

### 成果物

`docs/superpowers/specs/2026-06-20-grep-analyzer-refactor-findings.md` に診断レポートを出力する。

- 所見ごとに一意 ID（例 `NAME-01`, `STRUCT-03`, `SIMPL-02`, `CMT-04`）を採番。
- **重大度 × 労力**でランク付けした優先順位表を冒頭に置く。
- 各所見に before→after の具体スケッチを付け、合意の単位を明確にする。

## フェーズ2: 実装

- ユーザーがレポートを見て着手項目を選択（または「上位から」「全部」等の指示）。
- 各項目を **TDD**（test-driven-development スキル）で実施。挙動を変えない純粋
  リファクタを原則とする。
- 名前変更は参照箇所を含めて一括更新する。コメントは保守的に扱う。
- 挙動変更が必要な所見は、純粋リファクタと分離し、都度フラグを立ててユーザーに相談する。
- まとまった論理単位ごとに main へ直コミットする。

## 検証

- 各変更後に pytest 全件 green を確認する（`.venv` を wheelhouse から有効化、baseline 638 passed を維持）。
- 純粋リファクタ原則のため、テストの意味的変更が必要になった場合はリファクタではなく挙動変更として扱い相談する。

## 非目標（YAGNI）

- 新機能の追加。
- 挙動・出力フォーマットの変更（必要が判明した場合は別途相談）。
- 今回のゴールに無関係な大規模アーキテクチャ刷新。
