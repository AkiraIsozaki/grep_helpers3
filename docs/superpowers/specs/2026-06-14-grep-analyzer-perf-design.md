# grep_analyzer 60GB 走査 高速化 設計

- 日付: 2026-06-14
- 対象: `src/grep_analyzer`
- 動機: 60GB級ソース群（SJIS系が多い）への run が1日たっても終わらない。

## 1. 背景と問題

60GB のソースコーパスに対する run が24時間以上完了しない。コードを精査した結果、
速度を支配している要因は以下:

1. **`--jobs` 既定が 1**（`cli.py:43`）。Python 単一プロセスで 60GB を automaton 走査している。
2. **非ASCII記号による ripgrep prefilter の自滅**（`ripgrep.py:226`）。
   `scan_symbols`（全keyword × 全活性記号の union）に非ASCII記号が1個でも入ると、その hop 全体で
   prefilter が `None`（=全件走査）に落ちる。SJIS系コーパスで日本語識別子を追うと、ほぼ毎 hop これを踏み、
   rg による絞り込みが無効化されて 60GB を丸ごと Python 走査する。
3. **chardet を全バイトに実行**（`encoding.py:24`）。UTF-8 strict 失敗後、ファイル全体のバイトに対し
   純Python の `chardet.detect(data)` を実行。SJIS系=ほぼ全ファイルがこの経路に入る。`enc_memo` は
   keyword をまたいだ chardet 重複を防ぐが、ユニークファイルごとに全バイト1回は必ず払う。
4. **per-keyword prefilter の rg 追加起動**（`_lockstep.py:108-116`）。診断帰属のため hop ごとに
   rg を keyword 数 K 回 追加 spawn する。

確認済み事実:
- 同梱 `rg` は `available()` / sha256 / smoke すべて解決OK（`vendor/ripgrep/<arch>/rg`）。prefilter は本来発火可能。
- `scan_hop` は `multiprocessing.Pool.map` で順序保存 → `--jobs N` でも出力はバイト同一（CLI help にも明記）。

## 2. 設計方針

**バイト同一性（決定性）契約を既定で維持する。** 本コードベースは lock-step union 走査・per-keyword
prefilter・`enc_memo` を「逐次版とバイト同値」を守るために構築している。出力が変わる最適化は
**opt-in フラグ**として追加し、既定は現状とバイト同一を保つ。golden（TSV＋diagnostics 件数）テストは
無改変で通ることをリグレッション番人とする。

優先度順の対応:

| # | 項目 | コード変更 | 出力 | 既定 |
|---|------|-----------|------|------|
| ① | `--jobs N` 運用 | 不要 | 不変 | — |
| ② | 非ASCII記号でも prefilter を効かせる | あり | 実用不変※ | **ON** |
| B-1 | `--fast-encoding`（cp932優先短絡） | あり | フラグ時のみ変化 | OFF |
| B-2 | `--no-perkw-diag`（per-keyword rg 削減） | あり | フラグ時のみ変化（診断のみ） | OFF |
| ⑤ | `--max-depth` / `--exclude` / `--resume` 運用 | 不要 | 不変 | — |

※ ②の「実用不変」の正確な意味は 3.1 に定義。

## 3. 変更内容

### 3.1 ② 非ASCII記号でも prefilter を効かせる（既定ON・実用不変）

**現状** (`ripgrep.py:226`):
```python
if not all(s.isascii() for s in symbols):
    return None          # 非ASCII記号が1個でもあれば全件走査
```

**変更**: 諦めて全件走査する代わりに、非ASCII記号を**各候補エンコーディングのバイト列に符号化**して
rg に複数パターン（OR / union）で渡す。

- パターン集合 = 各 symbol について `{utf-8, cp932, euc-jp}` で `encode` した生バイト列の和。
  （これらは状態を持たない符号化で、`fallback_chain` の既定をカバーする。`latin-1` は多くの
  日本語記号を encode 不能なので、encode 例外時はその候補をスキップする。）
- ASCII symbol は従来どおり utf-8 1パターン（cp932/euc-jp/utf-8 で同一バイト）。
- パターンファイルは**バイナリ書き込み**にして非UTF-8バイトを載せる。改行(0x0A)区切りは安全
  （cp932/euc-jp の2バイト目に 0x0A は出現しない）。

**正当性（上位集合保証）の境界**:
- cp932 / euc-jp / utf-8 は状態を持たない符号化なので「復号テキストに記号 S が現れる ⟹
  `S.encode(enc)` がファイルのバイト部分列」が成立する。よって各ファイルの復号エンコーディングが
  `{utf-8, cp932, euc-jp}` のとき、rg の keep 集合は automaton ヒット集合の上位集合であり**出力不変**。
- **残余の理論穴**: あるファイルが utf-8/cp932/euc-jp strict のいずれでも復号できず、chardet が
  候補外のエンコーディング（特に `iso-2022-jp` のような状態あり符号化）を返した場合のみ、rg が
  取りこぼして出力が変わり得る。SJIS系コーパスでは稀（ほぼ cp932/euc-jp/utf-8）。
- **採用方針 = A（実用不変）**: この残余穴は文書化のうえ既定ON とする。完全な strict 保証
  （穴を閉じる）は全ファイルの復号試行という追加コストを要し、効果に見合わないため採らない。

**影響範囲**: `ripgrep.py` の `prefilter` / `_run_rg_list`（パターン生成とバイナリ書き込み）。
パターン符号化に使う候補エンコーディングは `prefilter` 引数で受け取り、`opts.encoding_fallback`
を渡す（呼び出し側 `_lockstep.py`）。

### 3.2 B-1 `--fast-encoding`（cp932優先短絡・opt-in）

**変更**: `encoding.py` の復号順を、fast モード時に以下へ:
```
utf-8 strict → fallback鎖 strict（cp932, euc-jp）→ chardet → latin-1 + replace
```
（非 fast は現状維持: `utf-8 → chardet → fallback鎖 → latin-1+replace`。）
妥当な cp932 ファイルは **chardet を一切呼ばない**。

**配線**:
- `EngineOptions.fast_encoding: bool = False` を追加。
- `decode_bytes` / `decode_with_memo` に `fast: bool = False` 引数を追加。
- `pipeline.run`（`decode_bytes`/`decode_with_memo` 呼出）、`_scan`（`file_meta`/`meta_via_memo`）、
  並列 worker（`_worker_init` の initargs に `fast` を追加）へ透過。
- CLI `--fast-encoding`（store_true）。

**出力差**: chardet が「最初に strict 復号できる fallback 候補」と異なる codec を当てたはずのファイルでのみ、
`encoding` 列 / `要確認` / `decode_replaced` が変化。既定OFF で golden 無改変。

### 3.3 B-2 `--no-perkw-diag`（per-keyword rg 削減・opt-in）

**変更**: `_lockstep.py:108-116` の per-keyword 再 prefilter（`keep_k = _rg.prefilter(...)`）を
フラグ時にスキップし、全 keyword へ共有 `pass_results` を渡す。

**効果と影響**: `absorb_results`（`_ingest.py:75-76`）は `if symbol not in scan_chase and
symbol not in scan_term: continue` で**自 keyword の記号だけを取り込む**ため、共有 `pass_results` を
渡しても **per-keyword TSV は不変**。変わるのは先頭の per-relpath 副作用（`encoding_of.setdefault` /
`decode_replaced` 診断）の帰属のみで、`encoding_of` はヒットしない relpath では TSV に使われない。
よって **B-2 で変化するのは `diagnostics.txt` の `decode_replaced` 帰属（件数/詳細）だけ**。
hop ごとの rg 追加起動 K回が撤廃される。

**配線**:
- `EngineOptions.perkw_diag: bool = True` を追加。
- CLI `--no-perkw-diag`（`dest="perkw_diag"`, `action="store_false"`）。

### 3.4 ① / ⑤ 運用（コード不要・文書化）

README / 本 spec に推奨実行例を記載:
```
grep_analyzer --jobs <コア数> --fast-encoding \
              --input ... --output ... --source-root ... \
              [--max-depth 4] [--exclude <vendor/生成物>] [--resume]
```
- `--jobs N`: Pool.map 順序保存で出力不変。単独で最大の効果。
- `--max-depth` 縮小: 間接参照を深追いしないなら hop 数（=再走査回数）を削減。
- `--exclude`: vendor/生成物/巨大バイナリを物理的に削り 60GB を縮める。
- `--resume`: keyword 単位チェックポイントで再実行時の全やり直しを回避。

## 4. テスト戦略

- **既定バイト同一**: 既存 golden（per-keyword TSV byte 一致＋diagnostics SUMMARY 件数）が
  ②導入後・B系フラグOFFで**無改変で通る**こと。②は既定ONなので、非ASCII記号を含む既存
  golden ケースで TSV が変わらないことを必ず確認する。
- **② 単体**: 非ASCII記号 × cp932/euc-jp/utf-8 で保存した小コーパスを用意し、prefilter keep 集合が
  automaton ヒット集合の上位集合であること（取りこぼし0）を検証。パターンのバイナリ書き込み・
  latin-1 encode 不能時のスキップも単体テスト。
- **B-1 単体**: fast モードで cp932 妥当ファイルが chardet を呼ばず cp932 採用になること（呼出回数を
  spy）。非 fast との出力差が「chardet が別 codec を当てるファイル」に限局することを最小ケースで確認。
- **B-2 単体**: フラグON で per-keyword TSV が OFF と byte 一致し、`diagnostics.txt` の decode_replaced
  のみ差が出ること。rg spawn 回数の削減（K→1）も確認。
- **並列整合**: `--jobs>1` で ② / B-1 が `--jobs 1` と出力一致（worker への透過配線の検証）。

## 5. 残余リスク

- ② の理論穴（chardet が状態あり符号化を返す稀ファイルで取りこぼし）。既定ON のため、該当が疑われる
  環境では `--no-...`（②を無効化する退避フラグ）の要否を実装時に再検討する余地あり。本 spec では
  退避フラグは YAGNI として持たないが、実装中に既存 golden で取りこぼしが出た場合は再考する。
- B-1 の chardet 短絡は「最初に strict 復号できる fallback 候補」を優先するため、euc-jp ファイルが
  cp932 strict でも（誤って）復号可能な場合に cp932 と誤判定し得る。これは fast モードの既知の
  トレードオフであり、フラグ説明に明記する。

## 6. スコープ外（YAGNI）

- ② の strict 保証（追加 decode パス）。
- chardet のサンプリング検出（`data[:64KiB]`）— B-1（cp932短絡）でSJIS系は十分高速化されるため、
  二重に持たない。必要なら将来別 spec。
- `--jobs` 既定値の変更（自動コア数検出）。運用フラグで足りるため既定は 1 のまま。
