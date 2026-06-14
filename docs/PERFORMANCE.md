# 大規模コーパス（数十GB級）での高速化ガイド

SJIS 系が多い 60GB 級ソース群で `grep_analyzer` を実用的な時間で回すための設定。
設計の背景は `docs/superpowers/specs/2026-06-14-grep-analyzer-perf-design.md` を参照。

## 推奨実行例

```
grep_analyzer \
  --jobs <物理コア数> \
  --decode-cache-dir /var/tmp/ga_decode_cache \
  --progress on \
  --input  <*.grep を置いたディレクトリ> \
  --output <出力先> \
  --source-root <ソースルート> \
  [--max-depth 4] \
  [--exclude '<vendor/生成物の glob>'] \
  [--resume] \
  [--fast-encoding] \
  [--no-perkw-diag]
```

## フラグの効果と出力への影響

| フラグ | 効果 | 出力 |
|---|---|---|
| `--jobs N` | 走査を N 並列化。`pool.map` は順序保存なので結果は不変。**単独で最大の効果**。 | バイト不変 |
| `--decode-cache-dir DIR` | 復号＋言語判定を「ファイル(mtime/size)単位で1回」に固定し、hop・worker・**run をまたいで再利用**。2 回目以降の run は変更の無いファイルを再復号しない。 | バイト不変 |
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
で概ね 1.5 倍）。不要になったら手動削除してよい。`--fast-encoding` の有無は名前空間で分離され、
同一ディレクトリを共有しても混ざらない。
