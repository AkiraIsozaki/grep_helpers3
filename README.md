# grep_analyzer

grep 結果を言語別に分類し、決定的 TSV を出力する道具でございます（直接ヒットに加え、不動点反復で間接参照まで追いかけます）。

---

えー、毎度バカバカしいお噺を一席。

八っつぁん「ご隠居、大変だ。60ギガもあるソースの山から『この定数、どこで使ってやがるんだ』てぇのを調べろと言われまして」

ご隠居「grep でもかけたらどうだい」

八っつぁん「かけましたよ。したらば path やら行番号やらが何万行。Java だか SQL だか シェルだか分からねえ行がドッと出てきて、おまけに中身は MS932 ときた。挙句『SEED の値を DERIVED に付け替えて、そいつをまた別の奴が使ってる』なんて間接の間接まで追えと言う。冗談じゃねえ」

ご隠居「それならいい道具があるよ。**grep_analyzer** てえんだ」

---

## こいつは何をするもんで

ご隠居曰く——

1. キーワードごとの grep 結果（`path:lineno:content` の行が並んだ `*.grep`）を受け取り、
2. 実ソースを開いて文字コードを見立て（UTF-8 → chardet → cp932/euc-jp → latin-1 の順）、
3. 言語ごとの分類器（tree-sitter の AST やら正規表現やら）で「宣言か、参照か、代入か」を見分け、
4. **直接ヒットだけでなく、定数の付け替え・別名経由の間接参照を不動点反復で追跡**し、
5. Excel でそのまま開ける**決定的な TSV**（BOM 付き UTF-8）に書き出す。

「決定的」てぇのがミソで、並列度をいくつにしようが**出力はバイト単位で同一**。今日流しても明日流しても同じ答えが出る。博打じゃねえんだ。

### 見立てのできる言語

java / c / proc（Pro\*C `.pc`）/ sql（PL/SQL 一族 `.pkb` `.pks` `.prc` ほか）/ shell / perl / groovy（`.gradle` 含む）/ typescript / tsx / javascript / python / jsp

拡張子で見当をつけ、中身でも裏を取ります（`.c` の中の `EXEC SQL` を見破る、なんて芸当も）。よそ様の拡張子は `--lang-map .inc=c` てな具合に教えてやっておくんなさい。

## 支度（インストール）

Python は **3.12** 縛り。外の網（ネットワーク）が使えねえ現場でも困らねえよう、車輪は `wheelhouse/` に、ripgrep の刃物は `src/grep_analyzer/vendor/` に、みんな同梱してございます。

```bash
pip install --no-index --find-links wheelhouse -e .        # 使うだけなら
pip install --no-index --find-links wheelhouse -e ".[dev]" # 開発もするなら（pytest 入り）
```

## 使い方

まず長屋の支度。キーワードひとつにつき grep 結果をひとつ、ファイル名がそのままキーワード名になります。

```bash
mkdir -p grep_inputs
grep -rn "SEED_VALUE" /path/to/src > grep_inputs/SEED_VALUE.grep
grep -rn "TAX_RATE"   /path/to/src > grep_inputs/TAX_RATE.grep
```

あとは木戸を叩くだけ。

```bash
python -m grep_analyzer \
  --input  grep_inputs \
  --output ga_out \
  --source-root /path/to/src
```

並列走査（`--jobs`、既定 auto=CPU 数）も進捗表示（`--progress`、既定 on・stderr のみ）も、黙ってて勝手にやります。

### 出てくるもの

| ファイル | 中身 |
|---|---|
| `<keyword>.tsv` | 本命の分類結果（BOM 付き UTF-8、Excel でそのまま開く） |
| `<keyword>.partNN.tsv` | 1,048,575 行を超えたときの Excel 互換分割 |
| `<keyword>.manifest.json` | その keyword の完了印と入力指紋（`--resume` の判定に使う） |
| `diagnostics.txt` | パースできなかった行、文字化け置換、大きすぎて飛ばしたファイル等の白状帳 |

### TSV の列

`keyword` `language` `file` `lineno` `ref_kind` `category` `category_sub` `usage_summary` `via_symbol` `chain` `snippet` `encoding` `confidence` の 13 列。

見どころは `ref_kind` と `chain` で——

```
SEED  python  {SRC}/m.py  1  direct             ...                      SEED@m.py:1
SEED  python  {SRC}/m.py  2  indirect:constant  ...  via_symbol=SEED     SEED@m.py:1 -> SEED@m.py:2
```

「SEED を DERIVED に付け替えて、その DERIVED をまた誰かが……」てぇ数珠つなぎが `chain` に矢印で残る寸法。どこの誰から回ってきた借金か、一目で分かろうてえもんです。

## 主だった木戸銭（オプション）

全部見たけりゃ `python -m grep_analyzer --help`。ここは主だったところだけ。

| オプション | 講釈 |
|---|---|
| `--max-depth K` | 間接参照を追う深さ（既定 10）。深追い無用なら下げる |
| `--exclude GLOB` / `--include GLOB` | 走査の的を絞る（`target/` などは既定で除外済み） |
| `--max-file-bytes N` | **既定 5MB 超は黙って飛ばす**（diagnostics に記帳）。連結 SQL の化け物を拾うなら上げる |
| `--resume` | 仕損じた続きから。済んだ keyword は入力指紋を照合して飛ばす |
| `--decode-cache-dir DIR` | 復号キャッシュを run 跨ぎで使い回す（二度目からがめっぽう速い） |
| `--stoplist FILE` | 追跡無用の記号を書き並べて追い出す |
| `--lang-map .ext=lang` | 拡張子→言語のお目付け直し |
| `--fast-encoding` | SJIS 主体なら速いが、**euc-jp 混在の長屋では使っちゃいけない**（黙って誤復号する） |

## 60GB の大ヤマに挑むなら

一晩明けても帰ってこねえ——なんてえ野暮を避ける知恵袋は **[docs/PERFORMANCE.md](docs/PERFORMANCE.md)** に一式まとめてございます。ripgrep の前捌き（総量 1GiB 超で自動発動）、復号キャッシュの置き場と容量（60GB の山なら 90GB ほど食う）、進捗の読み方まで、そちらをご覧じろ。

## 開発の衆へ

```bash
python -m pytest            # 全部（unit / integration / golden / perf）
python -m pytest tests/unit # 手早く
```

この長屋の掟は **TDD**。まず赤い提灯（失敗するテスト）を下げてから、青くする。golden テストは「出力バイト同一」の証文でございますから、出力を変える普請のときは覚悟してかかっておくんなさい。設計の経緯は `docs/superpowers/` の下に綴ってあります。

---

八っつぁん「へえ、大したもんだ。で、ご隠居、こいつの名は何てえんです」

ご隠居「grep_analyzer。grep の尻拭いから間接の間接まで、みんな**追って**くれる」

八っつぁん「そいつはありがてえ。あっしの借金も追わねえでもらいてえもんで」

お後がよろしいようで。
