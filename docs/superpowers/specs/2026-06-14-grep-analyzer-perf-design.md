# grep_analyzer 60GB 走査 高速化 設計（改訂版 / 批判レビュー反映）

- 日付: 2026-06-14
- 対象: `src/grep_analyzer`
- 動機: 60GB級ソース群（SJIS系が多い）への run が1日たっても終わらない。

## 0. 改訂履歴

初版は「非ASCII記号で死ぬ rg prefilter を多エンコーディングパターンで復活させる（②）」を
既定ONの出力不変策として中心に据えたが、**3つの独立した批判レビューで柱が崩れた**:

- **②は実現不能**: `decode(cp932)` は多対一（非可逆）。復号テキストの記号を re-encode しても
  元バイト列に戻らない（例: バイト `FA 4A`→`Ⅰ`→`87 54`）。NEC特殊/IBM拡張/ローマ数字など
  398 バイト列が該当し、automaton はヒットするが rg は取りこぼす＝**上位集合保証は偽**。さらに
  rg 14.1.1 は非UTF-8パターンファイルを rc=2 で拒否し、現状の全件走査に落ちる＝高速化ゼロ。
  → **②はドロップ**。
- **真の本丸を見落としていた**: `_FileCache` 予算 64MB に対しコーパス 60GB。decode/言語判定が
  hop・worker をまたいで再実行される。特に `--jobs>1` では pool.map に worker affinity が無く、
  同一ファイルが hop ごとに別 worker へ割り当たり、worker ローカルの `_WORKER_ENC`/`_WORKER_CACHE`
  で chardet・言語判定が**何度も再実行**される。これが 60GB×時間の主因。

本改訂は **decode/言語判定を「ファイルにつき run（実体は mtime/size）あたり1回」に固定する
永続デコードキャッシュ**を中心に据える。出力は不変。

## 1. 確定した事実（レビューで検証済み）

- 同梱 `rg` は解決OK。prefilter は 60GB>1GiB 閾値で自動ON だが、union に非ASCII記号が1個でもあると
  `ripgrep.py:226` で `None`（全件走査）に落ちる。SJIS系で日本語識別子を追うと「ほぼ毎 hop」全件走査。
- `scan_hop` は `pool.map`（順序保存）なので `--jobs N` でも**出力はバイト同一**。
- `enc_memo`/`_WORKER_ENC` は chardet 結果 `(enc, replaced)` をメモ化するが、**worker ローカル**かつ
  affinity 無しのため jobs>1 では再 chardet が起き得る。decode 本体・言語判定は毎 hop 再実行。
- `_FileCache` 64MB は 60GB に対し hit 率ほぼ0。`--jobs N` では予算が `//jobs` され実質1ファイル分。
- `_scan_one` は tree-sitter を `cache=` 無しで呼ぶため AST 言語は hop ごとに**全文再 parse**
  （`_scan.py:150-153`）。
- `max_file_bytes` 既定 5MB 超は**黙って除外**（診断1行のみ・`walk.py:181-183`）。
- per-keyword 再 prefilter は `restrict_to=union_keep`（縮小集合）に対してのみ走り、全コーパスは舐めない
  ＝コストは小（B-2 の効果は限定的）。

## 2. 設計方針

**バイト同一性（決定性）契約を既定で維持。** 出力が変わる最適化は opt-in フラグに限定し、既定は
現状とバイト同一を保つ。golden（per-keyword TSV byte 一致＋diagnostics SUMMARY 件数）をリグレッション
番人とし、無改変で通すことを各変更の受け入れ条件にする。

| # | 項目 | コード | 出力 | 既定 |
|---|------|-------|------|------|
| 1 | **永続デコードキャッシュ**（decode/言語判定を mtime/size 単位で1回） | あり | 不変 | ON |
| 2 | `--jobs N` ＋ `scan_hop` の `chunksize` 指定・arg 配列肥大の緩和 | あり | 不変 | jobs は引数 |
| 3 | `--max-file-bytes` 除外の可視化（警告/サマリ） | あり | 不変 | ON |
| 4 | B-1 `--fast-encoding`（cp932優先短絡・**配線全箇所**修正・波及明記） | あり | flag時変化 | OFF |
| 5 | B-2 `--no-perkw-diag`（per-keyword rg 削減・効果小） | あり | flag時変化（診断のみ） | OFF |
| — | ~~② 非ASCII prefilter 復活~~ | **ドロップ**（実現不能） | — | — |
| — | ①⑤運用（`--jobs`/`--max-depth`/`--exclude`/`--resume`） | 不要 | 不変 | — |

## 3. 変更内容

### 3.1 永続デコードキャッシュ（中心・出力不変）

**狙い**: 「read → decode → 言語/方言判定」を**ファイルにつき1回**だけ行い、hop・worker・run を
またいで共有する。現状の worker ローカル `_FileCache`/`_WORKER_ENC`（小予算・affinity無し）に代えて、
**プロセス横断で共有できる永続ストア**を置く。

**ストア構造**（`src/grep_analyzer/decode_cache.py` 新規）:
- ディレクトリ（既定 `spill_dir` 配下、無指定時は run 専用 temp。`--decode-cache-dir` で上書き可）。
- キー = `(abspath, st_mtime_ns, st_size)` のハッシュ。**mtime/size を含めるので run をまたいでも
  安全に再利用**でき、ソース変更時は自動的にミス（再 decode）。
- 値 = 復号済み UTF-8 テキスト本体（content ファイル）＋メタ `(enc, replaced, language, dialect)`。
  メタは content ファイル先頭の固定長 JSON ヘッダに格納（1ファイル1アーティファクトで原子的）。
- 書き込みは temp+rename で原子的。複数 worker が hop1 で同一ファイルを同時 decode しても
  idempotent（最後の rename が勝ち、内容は同一なので出力不変）。

**`_read_meta`（`_scan.py`）の置換**:
```
hit  → ヘッダからメタ＋本文を読むだけ（chardet なし・decode なし・言語判定なし）
miss → read_bytes → decode（enc_memo 経由で chardet）→ _meta_from_text（言語/方言判定）→ store.put → 返す
```
worker は共有ストア（ファイルシステム）を参照するので affinity 不要。`_WORKER_CACHE` は本ストアの
薄い in-memory L1（同一 worker 内の連続 hit 用）として残してよいが、永続層が真の単一情報源。

**出力不変の根拠**: ストアは「read_bytes→decode_bytes→_meta_from_text」の結果を**そのまま**保存・再生する
純キャッシュ。キーに mtime/size を含むためソース不変中は同一アーティファクトを返し、ミス時は現行と
同一経路で再計算する。よって TSV・diagnostics はバイト不変。

**テスト**:
- store hit/miss、mtime/size 変化での無効化、原子的書き込み、並列同時 put の idempotency。
- 既存 golden（jobs=1 / jobs>1）が無改変で byte 一致。
- decode/言語判定の呼び出し回数が「ユニークファイル数」に一致する（spy で hop をまたいだ重複0を検証）。

### 3.2 `--jobs N` ＋ scan_hop のスケーリング改善（出力不変）

- `pool.map(..., chunksize=K)` を指定（既定 chunksize=1 のファイル毎IPCを緩和）。chunksize は
  `len(scan_files)/(jobs*係数)` 程度の決定的な式で算出（順序保存は維持＝出力不変）。
- 毎 chunk・毎 hop で全 `scan_files` の arg タプル list を作り直しているコスト（`_scan.py:282-283`）を、
  hop 内で chunk をまたいで再利用できる形に整理（symbols だけ temp 経由で差し替え）。
- `--jobs` 既定は 1 のまま（自動コア数検出は YAGNI）。運用は README に推奨例。

### 3.3 `--max-file-bytes` 除外の可視化（出力不変）

- 除外件数・合計バイトを diagnostics SUMMARY の目立つ位置に出す（現状は detail 行のみ）。
- run 終了時に `walk_skipped_large` が >0 なら stderr に1行警告。閾値変更（既定引き上げ）はしない
  ＝出力不変。「60GBで大物を黙って落としている」自覚をユーザーに与えるのが目的。

### 3.4 B-1 `--fast-encoding`（opt-in・配線修正版）

- `encoding.py`: fast 時の復号順を `utf-8 strict → fallback鎖 strict(cp932,euc-jp) → chardet → latin-1+replace`。
- **配線は全 decode 箇所**: `pipeline.py:97/127`、`_seed.py`（seed 復号）、`_scan.py`（file_meta/meta_via_memo）、
  `_finalize.py`（indirect の encoding 列復号）、並列 worker（`_worker_init` initargs）。1箇所でも漏らすと
  enc_memo の first-writer-wins で同一 run 内に fast/非fast が混在し非決定になる（レビュー指摘）。
- **出力差の波及を明記**: 異なる採用エンコーディングは復号テキストを変え、`detect_language` 経由で
  `language/category/snippet/confidence` まで変わり得る（encoding 列だけではない）。
- 既定 OFF。`fast` は run 全体で定数。enc_memo/永続キャッシュのキーは内容同一なら不変だが、
  fast/非fast を同一キャッシュで混ぜないよう **キャッシュ名前空間に fast フラグを含める**。

### 3.5 B-2 `--no-perkw-diag`（opt-in・効果小）

- `_lockstep.py:108-116` の per-keyword 再 prefilter を flag 時スキップし共有 `pass_results` を全 keyword へ。
- per-keyword TSV は不変（`absorb_results` の記号フィルタで隔離・レビューで厳密確認済み）。変わるのは
  `diagnostics.txt` の `decode_replaced` 帰属と `encoding_of` メンバシップのみ（後者は `.get(exact relpath)`
  でしか読まれず TSV 不変）。
- 効果は ASCII-only hop に限定され小さい。優先度最下位。

## 4. テスト戦略（全体）

- **既定バイト同一**: 3.1〜3.3 導入後、既存 golden（jobs=1 / jobs>1）が**無改変で通る**。
- **永続キャッシュ単体**: 3.1 の項目別テスト（hit/miss/無効化/原子性/並列 idempotency/呼出回数）。
- **B-1 単体**: 全 decode 箇所への配線（seed/finalize 含む）、fast/非fast キャッシュ分離、fast での
  language 変化が category/snippet にも波及することを最小ケースで固定。
- **B-2 単体**: per-keyword TSV が flag ON/OFF で byte 一致、diagnostics の decode_replaced のみ差。

## 5. 残余リスク

- 永続デコードキャッシュは content（復号UTF-8）を disk に置くため、初回 hop で最大 ~1.5×コーパス分の
  書き込みが発生（SJIS 2byte→UTF-8 3byte）。hop≥2 で read+decode 再実行を相殺して回収する設計だが、
  ローカルSSDで hop が浅い場合は回収が薄い。`--decode-cache-dir` で配置を制御し、run 跨ぎ再利用で
  さらに回収する。効果はサブセット計測で確認する（実装後の検証ステップ）。
- B-1 の fast 短絡は euc-jp ファイルが cp932 strict で誤復号し得る既知トレードオフ。フラグ説明に明記。

## 6. スコープ外（YAGNI）

- ② 非ASCII prefilter（実現不能のためドロップ）。
- chardet サンプリング検出（永続キャッシュで再 chardet が消えるため不要）。
- `--jobs` 既定値の自動コア数検出。
- tree-sitter の hop 跨ぎ parse キャッシュ（巨大ファイルでメモリ破綻リスク。永続デコードキャッシュの
  効果を測ってから別 spec で判断）。
