# 大ヤマ（数十GB級）攻めの高速化ガイド

えー、README の続きの一席。SJIS 系が幅を利かせる 60GB 級のソースの山を、
`grep_analyzer` で日のあるうちに片付けるための知恵袋でございます。
普請の経緯（設計の背景）は `docs/superpowers/specs/2026-06-14-grep-analyzer-perf-design.md` をご覧じろ。

---

八っつぁん「ご隠居、例の道具、60ギガの山に放り込んだら一晩明けても帰ってこねえ」

ご隠居「そりゃお前さん、支度が悪い。まずはこの通りにやってごらん」

## 推奨実行例（そのまま貼れる版）

`grep_analyzer` をインストールした環境（venv 等）で、**上の3変数だけ**自分の値に書き換えて流す。
**出てくるものはすべて従来とバイト同一**——速くなるだけで、答えは一文字も変わらねえ。

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
  --decode-cache-dir "$CACHE" \
  --input "$GREP_IN" \
  --output "$OUT" \
  --source-root "$SRC"
```

並列走査（`--jobs`、既定 auto=CPU数）と進捗表示（`--progress`、既定 on）は黙ってて勝手にやります。
ripgrep の前捌き（prefilter）も 60GB なら自動で発動（閾値 1GiB・rg は同梱の刃物）。
walk の件数と hop 内の `scanning N/total` が stderr に出ますから、
「働いてるのか居眠りしてるのか」は一目で分かる寸法。
二度目からは同じ `--decode-cache-dir` を指しゃあ、変わってねえファイルの再復号は丸ごと省ける。

### さらに尻を叩きたい場合（出力が少し変わる opt-in）

ご隠居曰く——「ここから先は**答えが変わり得る**博打も混じるから、承知の上でやるんだよ」

SJIS 主体で chardet の見立てが重いなら `--fast-encoding`、間接参照を深追いしないなら
`--max-depth` を下げる。診断の per-keyword 帰属が無用なら `--no-perkw-diag`。
巨大な生成物の類は `--exclude` で木戸の外へ。

```bash
python -m grep_analyzer \
  --decode-cache-dir "$CACHE" \
  --fast-encoding \
  --max-depth 4 \
  --no-perkw-diag \
  --exclude 'node_modules/**' --exclude '**/*.min.js' \
  --input "$GREP_IN" --output "$OUT" --source-root "$SRC"
```

## 木戸銭それぞれの講釈（フラグの効果と出力への影響）

| フラグ | 講釈 | 出力 |
|---|---|---|
| `--jobs N` | 走査を N 人がかりにする（**既定 auto=CPU数**）。`imap_unordered` の帰り順がどうあれ relpath 集約後に並べ直すから、答えは寸分違わねえ。相長屋（共有マシン）で遠慮したいときだけ明示指定。 | バイト不変 |
| `--decode-cache-dir DIR` | 復号を「ファイル(mtime/size)単位で一度きり」に固定（言語の見立ては relpath 依存ゆえ毎回安価に引き直す）。hop・worker・**run をまたいで使い回す**。direct/seed/scan/finalize の全経路が同じ蔵を共有（realpath 正規化）。二度目の run は変わってねえファイルを復号し直さねえ。 | バイト不変 |
| `--decode-cache-max-bytes N` | 蔵の上限。あふれたら参照の古い順に蔵出し（get 時 touch の LRU 近似）。**run をまたぐなら掛けとくのが利口**（無制限だと下記 ~1.5× の勘定で際限なく肥える）。 | バイト不変（蔵出しは再復号に降格するだけ） |
| `--progress on/off` | walk 列挙中の件数と hop 内の途中経過を stderr へ（**進んでるか止まってるかが分かる**）。**既定 on**。静かにしてほしけりゃ `--progress off`。 | バイト不変（stderr のみ） |
| `--max-depth K` | 不動点 hop 数の上限。間接の深追いが無用なら下げて再走査を減らす。 | 追跡深さが変わる |
| `--exclude GLOB` | vendor/生成物/巨大バイナリを木戸の外へ出して総量を削る。 | 対象が変わる |
| `--resume` | 済んだ keyword は飛ばす。仕損じたときのやり直しが速い。 | 不変 |
| `--fast-encoding` | cp932/euc-jp を chardet **より先に** strict で当たり、まっとうな SJIS なら chardet を省く。SJIS 主体で効く。 | **変わり得る**（chardet なら別 codec を当てたはずのファイルで encoding 列・言語・分類が変わる） |
| `--no-perkw-diag` | hop ごとの per-keyword ripgrep 再走査（K 回）を省く。 | per-keyword TSV は**不変**。`diagnostics.txt` の `decode_replaced` 帰属だけ変わる |

既定（フラグ無し）の出力はすべて従来とバイト同一。`--fast-encoding` と `--no-perkw-diag` の
二つだけが、明示したときに出力（または診断）の変わる opt-in でございます。

## ご用心: `--max-file-bytes`（既定 5MB）

八っつぁん「ご隠居、でけえファイルが影も形もねえんですが」

ご隠居「それだ。既定じゃ **5MB を超えるファイルは黙って走査から外される**（`diagnostics.txt` の
`walk_skipped_large` に記帳はされる）。外したときは run の stderr に件数の断り書きが出る。
連結 SQL の化け物だの minified JS だのを取りこぼしたくなけりゃ `--max-file-bytes` を
上げるんだが、その分メモリと時間の払いは増えるよ」

## まず様子を見たいとき

進捗表示（既定 on）を眺めながら一回流してごらんなさい。見立てはこうで——

- walk が長々と無音 → I/O かファイル数の律速。`--exclude` で削る。
- hop 数が多く、毎 hop の `scanning N/total` がほぼ全件 → ripgrep の前捌きが効いてねえ
  （非 ASCII 記号を含む hop では prefilter が降りて全件走査になる、てえ既知の泣きどころ）。
  `--max-depth` を下げる、対象を絞る等で凌ぐ。
- 二度目の run が一度目よりめっぽう速い → `--decode-cache-dir` の使い回しが効いてる証拠。

## 蔵（永続キャッシュ）の切り盛り

`--decode-cache-dir` の蔵は run をまたいで使い回せる（鍵に mtime/size が入ってるから、
ソースをいじりゃ自動でミス＝復号し直し）。蔵には復号済みのテキストが溜まる勘定で、
SJIS の 2byte が UTF-8 の 3byte になって概ね 1.5 倍。**60GB の山なら最大 ~90GB に届き得る**。
run 跨ぎで使うなら `--decode-cache-max-bytes` で上限を切っとくのが安全でございます
（無指定は無制限）。蔵出しはキャッシュミス＝再復号に降格するだけで答えは不変。
用済みになったら手で消して構わねえ。`--fast-encoding` の有り無しは名前空間で蔵を分けてあるから、
同じディレクトリに同居させても混ざる心配は無用。

壊れた品（クラッシュ中の torn write 等）はヘッダの本文バイト長照合で見破って
自動でミス扱い＝復号し直し、金輪際信用しねえ（耐久性のための fsync はしてねえ＝純然たるキャッシュ）。
disk full 等で書込が仕損じたときは、run 仕舞いに stderr へ件数を白状します。

---

八っつぁん「へえ、二度目がこんなに速えとは。こいつぁ蔵の力だ」

ご隠居「だから言ったろう。**急がば蔵を建てろ**、てえんだ」

お後がよろしいようで。
