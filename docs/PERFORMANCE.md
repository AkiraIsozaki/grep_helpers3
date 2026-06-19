# 大規模コーパス（数十GB級）での高速化ガイド

SJIS 系が多い 60GB 級ソース群で `grep_analyzer` を実用的な時間で回すための設定。
設計の背景は `docs/superpowers/specs/2026-06-14-grep-analyzer-perf-design.md` を参照。

## 推奨実行例（そのまま貼れる版）

`grep_analyzer` をインストールした環境（venv 等）で、上の3変数だけ自分の値に書き換えて実行する。
**出力はすべて従来とバイト同一**（速くなるだけ）。

```bash
# ==== ここ3つだけ書き換える ====
SRC=/path/to/source_root        # 解析対象ソースのルート
GREP_IN=/path/to/grep_inputs    # キーワードごとの *.grep を置いたディレクトリ
OUT=$PWD/ga_out                 # 出力先（TSV / diagnostics.txt / manifest）

# 復号キャッシュの置き場。/var など共有/システム領域は使わない。
# 自分が書ける大容量パスにする（60GB コーパスで概ね ~90GB 使う＝復号テキストを貯める）。
# 既定は出力の隣。容量が足りなければスクラッチ/作業領域の絶対パスに変える。
CACHE=$OUT/../ga_decode_cache

mkdir -p "$OUT" "$CACHE"
python -m grep_analyzer \
  --jobs "$(nproc)" \
  --decode-cache-dir "$CACHE" \
  --progress on \
  --input "$GREP_IN" \
  --output "$OUT" \
  --source-root "$SRC"
```

ripgrep prefilter は 60GB なら自動 ON（閾値 1GiB・rg 同梱）。`--progress on` で walk 件数と
hop 内の `scanning N/total` が stderr に出るので、止まっていないか確認できる。
2 回目以降は同じ `--decode-cache-dir` を指せば、変更の無いファイルの再復号を丸ごと省ける。

### さらに速くしたい場合（出力が少し変わる opt-in）

SJIS 主体で chardet が重いなら `--fast-encoding`、間接参照を深追いしないなら `--max-depth` を下げる。
診断の per-keyword 帰属が不要なら `--no-perkw-diag`。巨大な生成物等は `--exclude` で削る。

```bash
python -m grep_analyzer \
  --jobs "$(nproc)" \
  --decode-cache-dir "$CACHE" \
  --progress on \
  --fast-encoding \
  --max-depth 4 \
  --no-perkw-diag \
  --exclude 'node_modules/**' --exclude '**/*.min.js' \
  --input "$GREP_IN" --output "$OUT" --source-root "$SRC"
```

## フラグの効果と出力への影響

| フラグ | 効果 | 出力 |
|---|---|---|
| `--jobs N` | 走査を N 並列化。`pool.map` は順序保存なので結果は不変。**単独で最大の効果**。 | バイト不変 |
| `--decode-cache-dir DIR` | 復号＋言語判定を「ファイル(mtime/size)単位で1回」に固定し、hop・worker・**run をまたいで再利用**。direct/seed/scan/finalize の全経路が同一キャッシュを共有する（realpath 正規化）。2 回目以降の run は変更の無いファイルを再復号しない。 | バイト不変 |
| `--decode-cache-max-bytes N` | 永続キャッシュの上限。超過時に古い順で退避（LRU）。**run をまたいで `--decode-cache-dir` を使うなら推奨**（無制限だと下記の ~1.5× footprint で無制限に肥大する）。 | バイト不変（退避は再復号に降格するだけ） |
| `--progress on` | walk 列挙中の件数と、hop 内の走査途中経過を stderr に出す（**進行中か停止中かが分かる**）。 | バイト不変（stderr のみ） |
| `--max-depth K` | 不動点 hop 数の上限。間接参照を深追いしないなら下げて再走査を減らす。 | 追跡深さが変わる |
| `--exclude GLOB` | vendor/生成物/巨大バイナリを物理的に除外し総量を削る。 | 対象が変わる |
| `--resume` | 完了済み keyword をスキップ。途中失敗時の再実行を高速化。 | 不変 |
| `--fast-encoding` | cp932/euc-jp を chardet **より先に** strict 試行し、妥当な SJIS では chardet を省く。SJIS 主体で効く。 | **変化し得る**（chardet が別 codec を当てたはずのファイルで encoding 列・言語・分類が変わる） |
| `--no-perkw-diag` | hop ごとの per-keyword ripgrep 再走査（K 回）を省く。 | per-keyword TSV は**不変**。`diagnostics.txt` の `decode_replaced` 帰属のみ変化 |

既定（フラグ無し）の出力はすべて従来とバイト同一。`--fast-encoding` と `--no-perkw-diag` のみ
明示時に出力（または診断）が変わる opt-in。

## 注意: `--max-file-bytes`（既定 5MB）

既定で **5MB を超えるファイルは走査対象から黙って除外**される（`diagnostics.txt` の
`walk_skipped_large` に記録）。除外が発生した run では stderr に件数警告が出る。巨大な
生成物・連結 SQL・minified JS などを取りこぼしたくない場合は `--max-file-bytes` を上げる
（その分メモリ・時間は増える）。

## まず計測したいとき

`--progress on` で 1 回回し、

- walk が長く無音 → I/O / ファイル数律速。`--exclude` で削る。
- hop 数が多く毎 hop の `scanning N/total` が全件に近い → ripgrep prefilter が効いていない
  （非 ASCII 記号を含む hop では prefilter が無効化され全件走査になる既知の制限）。
  `--max-depth` を下げる、対象を絞る等で緩和。
- 2 回目の run が 1 回目より大幅に速い → `--decode-cache-dir` の再利用が効いている。

## 永続キャッシュの運用

`--decode-cache-dir` のディレクトリは run をまたいで再利用される（キーに mtime/size を含むので
ソース変更は自動でミス＝再復号）。ディスクには復号済みテキストが溜まる（SJIS 2byte→UTF-8 3byte
で概ね 1.5 倍）。**60GB のコーパスなら最大 ~90GB に達し得る**ので、run 跨ぎで使うときは
`--decode-cache-max-bytes` で上限を設けるのが安全（無指定は無制限）。退避はキャッシュミス＝
再復号に降格するだけで出力は不変。不要になったら手動削除してよい。`--fast-encoding` の有無は
名前空間で分離され、同一ディレクトリを共有しても混ざらない。

破損したアーティファクト（クラッシュ中の torn write 等）はヘッダの本文バイト長照合で
自動的にミス扱い＝再復号され、信用されない（耐久性のための fsync はしていない＝純キャッシュ）。
書込が disk full 等で失敗した場合は run 終了時に stderr へ件数を警告する。
