# grep_analyzer コード健全性 診断レポート（フェーズ1）＋実装結果（フェーズ2）

## 実装結果サマリ（フェーズ2・2026-06-20）

11 コミットで実装。全工程で pytest `739 passed, 10 skipped` を維持（純粋リファクタ）。

**実装済（約40件）:**
- コメント是正: CMT-fixedpoint-01（矛盾コメント）, CMT-fixedpoint-02, CMT-toplevelcore-05, CMT-toplevelcore-01/03（provenance）
- classifiers: SIMPL-classifiers-01（DFS3重複）, -02（extract_tree骨格）, -03（mask×6）, -04（node_text×29）, -05（死にパラメータ）, NAME-classifiers-01/02/03
- T1 対称二重化: STRUCT-toplevelcore-01（provenance）, SIMPL-fixedpoint-02（ingest）, STRUCT-snippetpatterns-01（clamp）
- fixedpoint: SIMPL-fixedpoint-01, STRUCT-fixedpoint-01（_scan_one）, -02（scan_hop）, -03（union）, -04（import位置）, NAME-fixedpoint-01
- 構造分割: STRUCT-toplevelorch-01（cli _validate_args）, STRUCT-toplevelcore-02（decode_cache get）, STRUCT-snippetpatterns-03（ts_span）
- 簡素化/命名: SIMPL-toplevelorch-02/04, SIMPL-toplevelcore-02, SIMPL-toplevelcore-01（blank集約）, NAME-toplevelorch-01/02/03, NAME-toplevelcore-01/02/03/04, NAME-fixedpoint-03, NAME-snippetpatterns-01/02, SIMPL/CMT-snippetpatterns-01

**挙動変更（ユーザー承認の上で実施）:**
- SIMPL-snippetpatterns-02 / WARN-snippetpatterns-01: `re.IGNORECASE` 除去。大文字 SUB/CLASS/DEF の
  false-positive 終端を解消（特性化テスト付き・golden 不変）。baseline は 741 passed/10 skipped に

**見送り（挙動変更のため・ユーザー判断で見送り確定）:**
- SIMPL-toplevelcore-03（classify テーブル化）: module-global の monkeypatch 遅延束縛シームを壊す
- STRUCT-toplevelorch-03 / SIMPL-toplevelorch-01（walk 統合）: 意図的複製でパリティテスト保護・binary窓が8K/64Kと異なる挙動変更
- CMT-classifiers-03（re.VERBOSE）: 既存パターンの空白意味が変わる正規表現挙動リスク

**見送り（低価値・非該当、理由付き）:**
- SIMPL-toplevelcore-04: 1行スライスの抽出は無益＋直importは文書化済fast-path seam
- SIMPL-snippetpatterns-04: `# noqa: F401` 付き意図的 re-export
- SIMPL-fixedpoint-03: `_scan_file` はテスト使用中の互換entry（デッドでない）
- SIMPL-snippetpatterns-05: `GROOVY_LINE_CAP` は実使用中（監査のスコープ限定による誤検出）
- STRUCT-classifiers-02（registry移動）: base へは循環import不可・`__init__` registryは慣例的
- STRUCT-classifiers-03（regex位置）・STRUCT-toplevelorch-04（progress）・STRUCT-toplevelcore-03（spill境界）・NAME-fixedpoint-02: 低価値の整形
- CHG-fixedpoint-01: 欠陥でなく将来リファクタへの注意書き（変更不要）
- CMT「正当WHY」群: 保持（並行/キャッシュ/降格契約の必須文書）

**実装済（大規模構造・追加2件）:**
- STRUCT-classifiers-01（ast_base 分離）: AST走査/parse基盤を ast_base へ分離、importer 16箇所を追随
- STRUCT-toplevelorch-02（pipeline.run の _direct_hits_for_keyword 抽出）: cur_ctx 状態機械を分離、golden で挙動不変担保

---



- 日付: 2026-06-20
- 対象: `src/grep_analyzer/`（57 ファイル / 約5,400 LOC、`vendor/` 除く）
- 方法: パッケージ単位で並列 read-only 監査。命名・構造・シンプル化・コメント臭を白紙評価。
- baseline: `739 passed, 10 skipped`（実走確定）

## サマリと全体所見

所見総数 **約70件**（NAME 16 / STRUCT 17 / SIMPL 21 / CMT 19 + 挙動変更注意 2）。
重大度の内訳は high 2・medium 約20・low 約50。

**最も重要な発見（当初仮説の検証結果）:**

1. **命名は概ね健全。** 明白な命名臭は局所的（1文字変数、略語、`_AST_BINDING`/`_BINDING` の不統一など）で、ほぼすべて low/S。「名前設計に大きな問題がある」という当初の懸念は、コード全体では**支持されなかった**。
2. **長コメントの多数は正当な WHY/契約だった。** ReDoS 下限値・キャッシュ非決定契約・TOCTOU 降格契約・ASCII 語境界トレードオフなど、名前では表現不能な設計判断が大半。「長コメント＝名前設計の代償」という仮説は**大筋で支持されなかった**。ただし例外として、**陳腐化・矛盾したコメント**（CMT-fixedpoint-01/02）と、**構造の二重化を言葉で接合しているコメント**（provenance、clamp）は実在する。
3. **本当の改善余地は STRUCT/SIMPL に集中。** 横断テーマは「**対称・鏡像なロジックの二重実装**」と「**リテラルマスク/ノード文字列化の重複**」。ここを共通化すると、付随する説明コメントも自然に減る（＝当初の狙いは、命名ではなく構造の重複解消の側から達成される）。

**横断テーマ（パッケージをまたぐ同型の問題）:**

- **T1 対称ロジックの二重化**: `provenance._iter_dfs`（seed/子の到達処理）、`_clamp.clamp_lines`（上/下拡張）、`_ingest.ingest_one`（chase/terminal ループ）、`walk_files`/`_walk_classified`、`ts_classifier` の3 DFS、AST chaser の `extract_tree` 骨格。いずれも「ほぼ同一の2ブロック」を1つに畳める。
- **T2 リテラルマスクの重複**: `mask()` が SQL/Perl/Shell/Groovy chaser ＋ `regex_classifier._mask` ＋ `dispatch` の計6箇所で同型。`patterns/literal_masking.py` への集約候補。
- **T3 ノード文字列化の重複**: `node.text.decode("utf-8", "replace")` が AST chaser で **29箇所**（確認済み）。`node_text(node)` ヘルパに集約可能。
- **T4 陳腐化・矛盾コメント**: キャッシュ契約コメントが実装と食い違う（CMT-fixedpoint-01/02）。保守者を誤誘導するため優先是正。

## 優先順位表（ROI = 重大度 ÷ 労力 降順）

各所見のステータス: 未着手 / 即修正済 / 合意待ち / 実装済 / 見送り。初期値はすべて「未着手」。
S 級の局所修正は spec の二経路ルールにより合意を経ず即修正してよい（事後記録）。

| ID | 重大度 | 労力 | 区分 | 概要 | ステータス |
|----|--------|------|------|------|-----------|
| CMT-fixedpoint-01 | high | S | 即修正可 | キャッシュ namespace の矛盾コメント是正（lang_map） | 未着手 |
| SIMPL-classifiers-01 | high | M | 合意 | ts_classifier の3 DFS を単一ジェネレータに集約 | 未着手 |
| SIMPL-classifiers-03 | medium | S | 即修正可 | `mask()` ×6 を `mask_literals()` に集約 | 未着手 |
| SIMPL-classifiers-04 | medium | S | 即修正可 | `node_text()` で `.text.decode` ×29 を集約 | 未着手 |
| SIMPL-classifiers-05 | low→med | S | 即修正可 | sql_chaser の死にパラメータ `dialect` 除去 | 未着手 |
| SIMPL-fixedpoint-01 | medium | S | 即修正可 | decode_cache hit からの meta 再導出を共通化 | 未着手 |
| NAME-classifiers-01 | medium | S | 即修正可 | ハンドラ命名・可視性の統一（`handle_binding`） | 未着手 |
| CMT-toplevelcore-01 | medium | S | 即修正可 | decode_cache docstring の三重重複を集約 | 未着手 |
| CMT-fixedpoint-02 | medium | S | 即修正可 | `_state` の worker args 説明を現行へ更新 | 未着手 |
| SIMPL-snippetpatterns-01 | medium | S | 即修正可 | `_truncate_for_render` に早期 return を内包 | 未着手 |
| STRUCT-toplevelorch-01 | medium | M | 合意 | cli `main` から `_validate_args` を抽出 | 未着手 |
| STRUCT-toplevelorch-02 | medium | M | 合意 | pipeline `run` から `_build_direct_hits` 抽出 | 未着手 |
| STRUCT-toplevelorch-03 | medium | M | 合意 | walk_files/_walk_classified の二重実装解消 | 未着手 |
| STRUCT-toplevelcore-01 | medium | M | 合意 | provenance `_iter_dfs` の到達処理ヘルパ化 | 未着手 |
| STRUCT-toplevelcore-02 | medium | M | 合意 | decode_cache `get` の検証段を平坦化 | 未着手 |
| SIMPL-classifiers-02 | medium | M | 合意 | AST chaser `extract_tree` 骨格を base へ引上げ | 未着手 |
| STRUCT-classifiers-01 | medium | M | 合意 | ts_classifier から AST 走査基盤を分離 | 未着手 |
| STRUCT-fixedpoint-01 | medium | M | 合意 | `_scan_one` から AST 解決部を抽出 | 未着手 |
| STRUCT-fixedpoint-02 | medium | M | 合意 | `scan_hop` の並列/逐次を関数抽出 | 未着手 |
| SIMPL-fixedpoint-02 | medium | M | 合意 | `ingest_one` の chase/terminal ループ統合 | 未着手 |
| CMT-toplevelcore-03 | medium | M | 合意 | provenance コメントを STRUCT-01 と一体で削減 | 未着手 |
| CMT-classifiers-03 | medium | M | 合意 | regex ルールを `re.VERBOSE` 化しコメントを WHY に限定 | 未着手 |
| STRUCT-snippetpatterns-01 | medium | M | 合意 | `clamp_lines` の省略カウントをヘルパ化 | 未着手 |
| SIMPL-toplevelorch-01 | medium | M | 合意 | walk_files/collect_files の利用調査と整理 | 未着手 |

low 級（約50件）は付録にまとめる。

---

## 詳細所見

### 高優先（high）

#### CMT-fixedpoint-01 — キャッシュ namespace の矛盾コメント【high / S・即修正可】【検証済】
- 場所: `fixedpoint/_lockstep.py:48`（連動 `fixedpoint/_scan.py:262`）
- 問題: コメントは「`decode_cache_namespace` は fast/encoding_fallback **/lang_map** を畳み込む」と書くが、実装の `fp` は `fast` と `fallback` のみ（確認済）。`decode_cache_namespace` の docstring 自身は「lang_map は含めない」と正しく書いており**自己矛盾**。保守者を確実に誤誘導する。
- 改善: `_lockstep.py:48` の「/lang_map」を削除し「fast/encoding_fallback を畳み込む」に修正。コードは正しいのでコメントのみ是正。

#### SIMPL-classifiers-01 — ts_classifier の走査3重複【high / M・合意】
- 場所: `classifiers/ts_classifier.py:100-161`
- 問題: `node_at_line` / `binding_at_line` / `bindings_at_line` が同一の反復 DFS と同一順序キー `(行スパン, start_byte, end_byte, type)` を持ち、差は「単一最小採用 / 型フィルタ＋最小 / 型フィルタ＋全件」のみ。
- 改善: 内包ノードを yield する `_nodes_covering(root, target)` に集約し、3関数を薄い filter/reduce にする。順序キーも `_span_key` に一本化。

### 中優先（medium）— 即修正可（S）

#### SIMPL-classifiers-03 — リテラルマスクの6重複（T2）【medium / S】
- 場所: `sql_chaser.py:18`, `perl_chaser.py:17`, `shell_chaser.py:19`, `groovy_chaser.py:18`, `regex_classifier.py:71`, `dispatch.py:42`
- 問題: `pattern.sub(lambda m: " "*len(m.group(0)), line)` が key 違いで同型反復。
- 改善: `patterns/literal_masking.py` に `mask_literals(language, line)` を1本置き、各 `mask()` を delegate 化。

#### SIMPL-classifiers-04 — ノード文字列化の29重複（T3）【medium / S】【検証済】
- 場所: 全 AST chaser（c 4・java 5・python 5・javascript 11・typescript 4 = 計29、確認済）
- 改善: base か model に `node_text(node) -> str` を置き全置換。

#### SIMPL-classifiers-05 — sql_chaser の死にパラメータ【medium / S】
- 場所: `sql_chaser.py:24-30,33-41`
- 問題: `_extract_var_symbols(dialect, line)` の `dialect` 未使用（docstring も「dialect 無視」と明記）。shell_chaser の同名は dialect 分岐があり正当。
- 改善: SQL のみ `dialect` を落とすかヘルパを `extract` にインライン化。

#### SIMPL-fixedpoint-01 — decode_cache hit からの meta 再導出重複【medium / S】
- 場所: `fixedpoint/_scan.py:91-94` と `:159-165`
- 問題: 「hit→`text,enc,replaced`→`_meta_from_text` 再導出」と同一コメントが2箇所重複。
- 改善: `_meta_from_decode_hit(dhit, relpath, lang_map) -> 5tuple` を抽出し両所から呼ぶ。

#### NAME-classifiers-01 — ハンドラ命名・可視性の不統一【medium / S】
- 場所: `javascript_chaser.py:63` `handle_binding`（public）vs `_handle_ts`/`_handle_java`/`_handle_c`
- 改善: 役割を表す名（例 `handle_js_binding`）に揃え、共有意図を名前で表現。

#### CMT-toplevelcore-01 — decode_cache docstring の重複【medium / S】
- 場所: `decode_cache.py:1-20`（連動 146-147）
- 問題: 「language/dialect は relpath 依存だからキャッシュしない」という同一要点が冒頭・6-8行・146-147 で三度重複。WHY 自体は正当（realpath 共有時の先勝ち非決定）。
- 改善: WHY の核を1段に集約し `put` 側コメントは参照に短縮。理由は残し重複のみ削減。

#### CMT-fixedpoint-02 — `_state` の worker args 説明が陳腐化【medium / S】
- 場所: `fixedpoint/_state.py:4-5`
- 問題: 「worker に `(relpath, abspath, symbol_list, lang_map, fallback)` を渡す」と書くが、実際は `(relpath, abspath, sig, sym_path)`（`_scan.py:310`）で lang_map/fallback は `_worker_init` で固定。
- 改善: 現行 worker args に更新するか、不変条件のみ述べて具体 tuple は `_scan.py` に一元化。

#### SIMPL-snippetpatterns-01 — truncate 判定の二重化【medium / S】
- 場所: `snippet/_clamp.py:63-65` と `:24-42`
- 問題: 「escape 後長 > char_max」判定が呼び出し側と `_truncate_for_render` 内で二重。
- 改善: `_truncate_for_render` に「未超過ならそのまま返す」早期 return を内包し、呼び出し側の三項演算子を単純化。

### 中優先（medium）— 合意（M）

#### STRUCT-toplevelorch-01 — cli `main` の責務過多【medium / M】
- 場所: `cli.py:133-202`
- 問題: parse・20本超のバリデーション（約60行）・opts 生成・run を1関数に同居。
- 改善: `_validate_args(parser, args)` を抽出し `main` を parse→validate→opts→run に圧縮。

#### STRUCT-toplevelorch-02 — pipeline `run` の direct 構築ループ【medium / M】
- 場所: `pipeline.py:105-199`（`run` は215行）
- 問題: resume 判定・指紋計算・relpath キャッシュ・復号・言語判定・分類・Hit 生成・診断発火を二重ループに同居。
- 改善: `_build_direct_hits(...)` を抽出し `run` を walk→direct→states→fixedpoint→finalize→diag の骨格に。

#### STRUCT-toplevelorch-03 — walk の二重実装（T1）【medium / M】
- 場所: `walk.py:142-172`（`walk_files`）と `:188-235`（`_walk_classified`）
- 問題: stat→S_ISREG→large→binary→realpath dedup の判定列をほぼ複製（コメント自身が6回「walk_files と同一」と明言）。
- 改善: `_walk_classified` を唯一実装にし `walk_files` を薄いアダプタ化。※ `_is_binary`(NUL のみ) と `_classify_bytes`(BOM も unsafe) の集合同一性をテストで確認（SIMPL-toplevelorch-01 と連動）。

#### STRUCT-toplevelcore-01 — provenance `_iter_dfs` の到達処理二重展開（T1）【medium / M】
- 場所: `provenance.py:71-113`
- 問題: seed フレームと子フレームで「target 判定→max_depth 判定」の到達処理を二重に手展開。片方だけ直す保守事故を招く。
- 改善: `_visit(occ, path, depth) -> "appended|cut|descend"` に括り出し seed/子で同一呼び出し。診断 emit 順は byte 不変をテストで担保。

#### STRUCT-toplevelcore-02 — decode_cache `get` の検証段【medium / M】
- 場所: `decode_cache.py:100-142`
- 問題: 読込・ヘッダ分割・JSON parse・型検証・sig 再検証・blen 検証・本文 decode・キー取り出しの8段を1関数（約40行）に直列展開。
- 改善: `_parse_header(raw, sig) -> dict|None` と本文照合を分離し3段に縮約。破損 discard ポリシーは不変。

#### SIMPL-classifiers-02 — AST chaser `extract_tree` 骨格の共有（T1）【medium / M】
- 場所: `python_chaser.py:67`, `java_chaser.py:50`, `c_chaser.py:56`, `javascript_chaser.py:90`, `typescript_chaser.py:36`
- 問題: 5 chaser の `extract_tree` が「4リスト初期化→`bindings_at_line` ループ→handler→`dedup_symbols`」を完全共有。差は `_BINDING` と handler のみ。
- 改善: base に `run_field_chase(root, lineno, binding_set, handler)` を置き、handler 署名を `(node, ctx)` に揃える。

#### STRUCT-classifiers-01 — ts_classifier の責務分離【medium / M】
- 場所: `classifiers/ts_classifier.py`（224行）
- 問題: 分類器（`classify_ts`）と AST 走査基盤（`*_at_line`/`parse_tree`/parser キャッシュ）が同居。chaser が分類器から走査関数を import する不自然な依存。
- 改善: AST 走査・parse 基盤を `ast_base.py` 等へ分離。SIMPL-classifiers-01/02 と一体で実施すると効果大。

#### STRUCT-fixedpoint-01 — `_scan_one` の責務過多【medium / M】
- 場所: `fixedpoint/_scan.py:178-226`
- 問題: meta 取得＋OSError 降格・行走査・AST lazy parse・angular テンプレート span 分岐・chase 抽出を全担。
- 改善: AST 解決を `_resolve_chase_symbols(language, text, i, parse_state)` に抽出し、走査ループは「symbol→cs を引く」だけに。

#### STRUCT-fixedpoint-02 — `scan_hop` の並列/逐次同居【medium / M】
- 場所: `fixedpoint/_scan.py:354-422`
- 問題: chunk 分割・並列(temp file＋imap)・逐次・集約再ソートが1関数。並列/逐次ブランチは同型。
- 改善: `_scan_chunk_parallel` / `_scan_chunk_serial` に抽出し `scan_hop` は chunk ループ＋集約に。

#### SIMPL-fixedpoint-02 — `ingest_one` の chase/terminal ループ統合（T1）【medium / M】
- 場所: `fixedpoint/_ingest.py:38-61`
- 問題: chase と terminal の2ループが同型（差は default kind と追加先 set のみ）。
- 改善: `(part.chase,"var",chase_active,chase_done)` / `(part.terminal,"getter",terminal_active,terminal_done)` を回す1ループに畳む。

#### CMT-toplevelcore-03 — provenance コメント（STRUCT-01 と一体）【medium / M】
- 場所: `provenance.py:81-87, 101-109`
- 問題: 存在しない再帰版 `_dfs` を参照する手展開の対応注釈。STRUCT-toplevelcore-01 のヘルパ抽出で大半が不要になる。
- 改善: STRUCT-01 と同時に削減。「診断 emit 順を前順と一致させる」WHY 1行のみ残す。

#### CMT-classifiers-03 — regex ルールの説明過多【medium / M】
- 場所: `regex_classifier.py:9-10,16,26-28,76,85` ほか
- 問題: `:=` 優先・`==`除外・裸 `<>` 除外などの説明が、正規表現が非自明（`(?<![-=])<(?!=)` 等）であることの裏返し（一部は設計の代償）。順序依存もコメントで支える脆さ。
- 改善: `re.VERBOSE` 化＋名前付きグループで意図をパターンに織り込み、コメントを WHY（golden 順序）に限定。

#### STRUCT-snippetpatterns-01 — `clamp_lines` の責務過多（T1）【medium / M】
- 場所: `snippet/_clamp.py:54-89`
- 問題: 事前 truncate・上下交互拡張・省略カウント・render を1関数に持ち、`above_count`/`below_count` を鏡像式で重複計算（L73-74 と L81-82）。
- 改善: 省略カウントを `_omitted(up_idx, down_idx, span_start, span_end)` に抽出。上下優先順位は保持。

#### SIMPL-toplevelorch-01 — walk legacy 経路の整理【medium / M】
- 場所: `walk.py:142-185`（`walk_files`/`collect_files`）
- 問題: pipeline は `collect_files_ex` のみ使用。legacy 経路がテスト専用なら二重実装はデッドコードの維持コスト。
- 改善: 利用箇所を grep 確認し、テスト専用なら `_walk_classified` に一本化して削除/アダプタ化。

---

## 付録: low 級所見（約50件・簡潔版）

**命名（NAME, low/S 中心）**
- NAME-toplevelorch-01 `pipeline.py:84-88` `explicit`/`effective` → `use_rg_override`/`use_rg`
- NAME-toplevelorch-02 `output_writer.py:143` `L`/`n` → `rows_per_part`/`total`
- NAME-toplevelorch-03 `pipeline.py:75` `_walk_cb`/`n` → `count`
- NAME-toplevelcore-01 `model.py:20` 引数 `consts` → `constants`（フィールド名と統一）
- NAME-toplevelcore-02 `model.py:26` `uniq` → `ordered_uniq`（順序保持が契約）
- NAME-toplevelcore-03 `spill.py:19,23` `_enc`/`_dec` → `_escape`/`_unescape`
- NAME-toplevelcore-04 `decode_cache.py:81` `_stat` → `_file_sig`
- NAME-fixedpoint-01 `_scan.py:78` `meta_cached` → `meta_via_decode_cache`
- NAME-fixedpoint-02 `_scan.py:354` `nchunks` 要求値/実値の命名統一
- NAME-fixedpoint-03 `_finalize.py:19` `_live_edges` → `_uncapped_edges`（`live` の語が別概念と衝突）
- NAME-classifiers-02 `c/java _AST_BINDING` → `_BINDING`（全 chaser AST なので接頭辞無意味）
- NAME-classifiers-03 `regex_classifier.py:38` `_apply` → `_classify_by_rules`
- NAME-snippetpatterns-01 `_heuristic.py:18` `paren_depth` → `bracket_depth`（`[`/`{` も数える）
- NAME-snippetpatterns-02 `_clamp.py:7-9` `ELL` → `ELLIPSIS`
- NAME-snippetpatterns-03 `_clamp.py:73-88` `above_count`/`top_k` の用語統一

**構造（STRUCT, low）**
- STRUCT-toplevelorch-04 進捗報告が pipeline の直接 print と Progress に二分（M）
- STRUCT-toplevelcore-03 `spill.py` に直列化/EdgeStore/PID 掃除の3責務同居（境界指摘のみ）
- STRUCT-classifiers-02 `__init__.py` の registry を `base`/`registry.py` へ集約
- STRUCT-classifiers-03 `regex_classifier.py` のルール定義位置の不統一（並べ替え）
- STRUCT-fixedpoint-03 `_budget_control.py:71-72,94-95` の union 集計重複 → `_union_load(states)`
- STRUCT-fixedpoint-04 `_scan.py:21-31` `read_bytes_with_sig` が import 群を分断（PEP8）
- STRUCT-snippetpatterns-02 `_clamp.py:71-86` 上下拡張ブロックの対称重複（T1）
- STRUCT-snippetpatterns-03 `_ts.py:76-116` `ts_span` のセット選択を `_resolve_sets` に抽出

**シンプル化（SIMPL, low）**
- SIMPL-toplevelorch-02 `pipeline.py:255` `getattr(decode_cache,"put_failures",0)` → 直接アクセス（属性は常に存在）
- SIMPL-toplevelorch-03 `cli.py` lang-map パース/検証の二重 split を統合
- SIMPL-toplevelorch-04 `output_writer.py:172` `__import__(...)._ITEMS_PER_MB` → 通常 import
- SIMPL-toplevelcore-01 改行保存空白化 `_blank` の重複（proc/embed）を共通化
- SIMPL-toplevelcore-02 `decode_cache.py` `_scan_total` と `_enforce_budget` の glob+stat 重複
- SIMPL-toplevelcore-03 `classify.py:30-44` sql/perl/groovy 分岐をテーブル駆動化
- SIMPL-toplevelcore-04 `chase.py` クランプ重複と言語ディスパッチの非対称（直 import）
- SIMPL-fixedpoint-03 `_scan.py:229` `_scan_file` 後方互換シムの利用調査（テスト専用なら整理）
- SIMPL-fixedpoint-04 `_options.py:34-35` test-only フィールドの本番常駐分岐（要相談）
- SIMPL-snippetpatterns-02 `snippet_boundaries.py:14` 不要な `re.IGNORECASE`（⚠️下記）
- SIMPL-snippetpatterns-03 `_clamp.py:32` `budget<0` 防御分岐（テスト依存確認）
- SIMPL-snippetpatterns-04 `_sanitize_line.py:8` 未使用 `SEP` 再 export の確認
- SIMPL-snippetpatterns-05 `symbol_extraction.py:39` `GROOVY_LINE_CAP` 定義と利用の分離

**コメント（CMT, low — 大半は「正当WHY・保持」判定）**
- 正当WHY（保持推奨）: CMT-toplevelorch-02（cli ガード理由）, CMT-toplevelcore-02（ReDoS 下限 800）, CMT-toplevelcore-04（automaton ASCII 語境界）, CMT-fixedpoint-03/04（per-kw 絞り・hot path 判断、圧縮余地のみ）, CMT-classifiers-01/02（遅延 import・OOM 降格）, CMT-snippetpatterns-01/02/04（escape 順序・窓幅根拠・Groovy cap）
- 代償（軽微・削減候補）: CMT-toplevelorch-01（pipeline relpath キャッシュ説明、STRUCT-02 と連動）, CMT-toplevelorch-03（dispatch のマスク方針言及）, CMT-toplevelcore-05（spill「完全に可逆」の空強調）, CMT-snippetpatterns-03（`_clamp.py:63` 重複インライン）

## ⚠️ 挙動変更注意（純粋リファクタで直せない／要判断）

- **CHG-fixedpoint-01** `_scan.py:387` 並列 automaton signature が `json.dumps(chunk)`（`sort_keys` 無し＝リスト順依存）。現状はバグでないが、chunk 構築順を変える変更は再構築頻度（性能）に影響。リファクタ時は `_chunk_signature(chunk)` に括り「順序込みで決定的」と明記、値は変えない。
- **WARN-snippetpatterns-01** `snippet_boundaries.py:14` の `re.IGNORECASE` 除去（SIMPL-snippetpatterns-02）は理論上は出力不変だが、大文字混じり語で停止判定が変わる可能性ゼロでない。`heuristic_span` のスナップショット差分テストで不変確認後に適用。

## 次アクション（フェーズ2の提案）

1. **即修正可（S, 合意不要）の塊**を先行: CMT-fixedpoint-01（矛盾コメント）、SIMPL-classifiers-03/04/05（マスク/ノード文字列化/死にパラメータ）、各種 NAME low/S。TDD で baseline 維持。
2. **classifiers の構造改善**（SIMPL-01/02 + STRUCT-01）を一体で。横断効果が最大。
3. **対称ロジック二重化（T1）**を順に: provenance、clamp、ingest、walk、scan_hop/_scan_one。
4. 挙動変更注意の2件は最後に、専用テストを足してから。
