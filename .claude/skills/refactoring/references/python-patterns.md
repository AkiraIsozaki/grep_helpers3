# Python リファクタリング パターン集

`grep_analyzer` を題材にした、9原則それぞれのパターン・アンチパターン・やりすぎ注意の集約。
命名の詳細規約（フルスペル原則・語彙固定・rename 除外）は `coding-conventions` スキルを参照。

## 関心の分離と可視性

### パターン: `_` 接頭辞でモジュール内部を宣言する

Python の非公開は規約ベース。「このモジュールの内部実装」は `_` 接頭辞で意思表示する。

```python
# ❌ Anti-pattern: モジュール内でしか使われないのに public 名
def strip_bom(line: bytes) -> bytes: ...      # 他モジュールから import されていない

# ✅ Pattern: モジュール内 private（Grep で外部使用が無いことを確認してから）
def _strip_bom(line: bytes) -> bytes: ...
```

### パターン: `__all__` で公開面を宣言する

公開 API を持つモジュールでは `__all__ = ["extract_snippet", "SnippetResult"]` のように
「何が契約か」を先頭で明示する。`__all__` に無い名前は内部実装とみなせる。

### 注意: モジュール跨ぎ helper は public 名のまま

`coding-conventions` の規約どおり、他モジュールから import される helper に
`_` を付けてはいけない（`_file_meta` → `file_meta` の実例あり）。

```python
from grep_analyzer.walk import _file_meta  # ❌ 「モジュール内 private」の意味が破れる
from grep_analyzer.walk import file_meta   # ✅ 共有 helper は public 名のまま
```

### パターン: 層分離を守る（葉→根の一方向）

`patterns/*` は葉（何にも依存しない）。下位が `pipeline` / `cli` を import したら層違反。

```python
from grep_analyzer.pipeline import PipelineState  # ❌ 下位からの上位 import は循環の温床
def classify_line(line: str, dialect: Dialect) -> Category: ...
# ✅ 必要な値だけを引数で受け取る（依存は受け取る・結果は返す）
```

---

## 不変性

### パターン: frozen dataclass を既定にする

生成後に変更されないデータは `frozen=True` で固定する。multiprocessing への
受け渡しも安全になる。

```python
# ❌ @dataclass のみ — 生成後に書き換えられる余地を残す
# ✅ Pattern: 不変な値オブジェクト
@dataclass(frozen=True)
class FileMeta:
    relpath: str
    encoding: str
    size_bytes: int
```

### パターン: 更新は `dataclasses.replace` で新インスタンスを作る

```python
# ❌ Anti-pattern: frozen を諦めて可変にする
meta.encoding = "ms932"

# ✅ Pattern: 差分を指定して新しいインスタンスを生成
meta = dataclasses.replace(meta, encoding="ms932")
```

### パターン: 変更しないコレクションは tuple、定数は Final

```python
# ❌ Anti-pattern: 変更しないのに list / 素の代入
SUPPORTED_EXTENSIONS = [".sql", ".sh", ".java"]

# ✅ Pattern: tuple + Final で「変更しない」を型に載せる
SUPPORTED_EXTENSIONS: Final[tuple[str, ...]] = (".sql", ".sh", ".java")
```

### アンチパターン: 可変デフォルト引数

```python
def collect_hits(hits: list[Hit] = []) -> list[Hit]: ...   # ❌ 呼び出し間で共有される
def collect_hits(hits: list[Hit] | None = None) -> list[Hit]: ...  # ✅ None を番兵に
```

---

## プリミティブ執着の回避

### パターン: NewType でランタイムコスト無しに区別する

意味の異なる str/int の取り違えを型チェッカで検出できるようにする。

```python
# ❌ Anti-pattern: relpath と abspath がどちらも str で、逆に渡しても気づけない
def read_snippet(path: str, other: str, lineno: int) -> str: ...

# ✅ Pattern: NewType（実行時は素の str のまま。ゼロコスト）
RelPath = NewType("RelPath", str)
AbsPath = NewType("AbsPath", str)

def read_snippet(relpath: RelPath, root: AbsPath, lineno: int) -> str: ...
```

### パターン: 閉じた区分は Enum にする

```python
# ❌ Anti-pattern: 文字列リテラルの比較 — タイポしても実行時まで気づけない
if dialect == "orcale": ...   # typo

# ✅ Pattern: Enum（StrEnum なら TSV 出力への文字列化も自然）
class Dialect(StrEnum):
    ORACLE = "oracle"
    POSTGRES = "postgres"

if dialect is Dialect.ORACLE: ...
```

### パターン: 型なしタプルを dataclass に包む

```python
# ❌ list[tuple[str, int, str]] — 各要素の意味は呼び出し側の記憶頼み
# ✅ Pattern: 名前付きの小さな値オブジェクト
@dataclass(frozen=True)
class Occurrence:
    relpath: str
    lineno: int
    symbol: str

def find_occurrences(text: str) -> list[Occurrence]: ...
```

検証（不変条件）が要る場合は `dataclass(frozen=True)` + `__post_init__` で
`raise ValueError` する（例: `Span` の `0 <= start <= end`）。

**型の選択指針**: 区別だけ → `NewType`／複数フィールド・検証 → `dataclass(frozen=True)`／
閉じた区分 → `Enum`。

---

## 名前設計

詳細は **`coding-conventions` スキルに全て定義済み**（フルスペル原則と略語ホワイトリスト、
`is_*`/`has_*`/`should_*` の述語統一、`relpath`/`lineno` 等のドメイン語彙固定、rename 除外規則）。
ここでは重複記述しない。分析時はそちらを読み込み、違反を列挙すること。

---

## インターフェース（Protocol / ABC）

### パターン: 構造的部分型の Protocol を第一候補にする

テストで差し替えたい依存は Protocol で抽象化する。既存クラスは継承宣言なしで適合する。

```python
# ❌ Anti-pattern: 外部プロセス起動の具象実装に直接依存 — テストで実 rg が必要になる
def run_search(query: str) -> list[Hit]:
    return RipgrepRunner().search(query)

# ✅ Pattern: Protocol に依存し、実体は引数で受け取る
class SearchRunner(Protocol):
    def search(self, query: str) -> list[Hit]: ...

def run_search(query: str, runner: SearchRunner) -> list[Hit]:
    return runner.search(query)
```

ABC は「明示的な継承階層 + 共通実装の共有」が必要な場合のみ。差し替え可能性の表現だけなら
Protocol で足りる。

### アンチパターン: 過度な抽象化

```python
# ❌ Anti-pattern: 実装が1つで差し替え要件も無いのに Protocol を切る
class SymbolSorter(Protocol):
    def sort(self, symbols: list[str]) -> list[str]: ...

# ✅ Pattern: 素の関数で十分
def sort_symbols(symbols: list[str]) -> list[str]:
    return sorted(symbols)
```

**導入の判断基準**（1つも当てはまらなければ導入しない）:
- テストで差し替えたい（ファイル I/O、外部プロセス、時刻）
- 実装を差し替える実際の要件がある（本番 vs テスト、方言別の実装）
- プラグインポイントとして明示的に設計している

---

## ドキュメントとの乖離

### パターン: 責務の変更は docstring と設計文書に同時反映

モジュール分割後に docstring が旧責務（例:「スニペット抽出と境界検出を行う」）のまま
残っていたら、実態に合わせて更新する（「境界検出は snippet_boundaries に委譲する」、
spec 参照は末尾 `Related: spec §X` に集約 — `coding-conventions` の形式）。

変更のたびに `docs/superpowers/specs/` の該当文書と照合し、
古い関数名・旧構成の記述を残さない（SKILL.md フェーズ2の早見表を参照）。

---

## 重複コードの抽出

### パターン: 繰り返しの try-except + 診断記録を高階関数へ

```python
# ❌ Anti-pattern: 「捕捉 → diagnostics 記録 → 既定値」の同じ構造が3関数以上に繰り返される
def read_file_a(relpath: str) -> str:
    try:
        return decode_file(relpath)
    except UnicodeDecodeError as e:
        diagnostics.record(relpath, e)
        return ""

# ✅ Pattern: 共通のラッパーに集約（3箇所目が出た時点で）
def _with_decode_diagnostics(relpath: str, action: Callable[[], T], default: T) -> T:
    try:
        return action()
    except UnicodeDecodeError as e:
        diagnostics.record(relpath, e)
        return default
```

### パターン: Rule of Three と「同一知識か」の確認

`coding-conventions` の DRY 誤適用防止と同一基準。抽出前に必ず確認する:

```
1回目: そのまま書く
2回目: 「もしかして重複?」と気づく（まだ寄せない）
3回目: (1) 同一知識か（片方だけ変わるシナリオが想像できるなら寄せない）
        (2) 同じ用語で説明できるか
        を確認してから抽出する
```

「偶然2箇所が同じ形」を寄せると、片方の仕様変更でもう片方が壊れる。

---

## 関数の長さと複雑度

### パターン: 長い関数を意図を表す名前の小さな関数に分割

40行の関数（検証・走査・TSV 書き出しが混在）は、責務ごとに意図を表す名前の
`_` 接頭辞関数へ分割する。

```python
# ✅ Pattern: 分割後 — 各行がタスクを1文で語る
def scan_directory(root: str) -> None:
    if not _can_access(root):
        return
    targets = _collect_target_files(root)
    _write_results(targets)
```

### パターン: 早期 return でネストを解消

if の3段ネストは、ガード節の連続に書き換えて本体を最外段に置く。

```python
# ✅ Pattern: ガード節でフラット化 — 本体に到達する条件が明確
def process_file(relpath: str) -> None:
    if not os.path.exists(relpath):
        return
    if not _is_supported(relpath):
        return
    if _is_excluded(relpath):
        return
    ...  # 本体
```

**目安**: 関数本体 20〜30 行以内、1モジュール 300 行以内（超えたらサブパッケージ化を検討）。

---

## エラー処理の設計

### パターン: 捕捉する例外型を必要最小限に絞る

```python
# ❌ Anti-pattern: Exception を捕捉 — バグ（TypeError 等）まで飲み込む
try:
    text = decode_file(relpath)
except Exception:
    text = ""

# ✅ Pattern: 起こり得る具体的な例外だけ捕捉し、それ以外は上位へ伝播
try:
    text = decode_file(relpath)
except (UnicodeDecodeError, OSError) as e:
    diagnostics.record(relpath, e)
    text = ""
```

### アンチパターン: 握りつぶし

```python
except OSError:
    pass                            # ❌ 障害が「静かな欠落」になる
except OSError as e:
    diagnostics.record(relpath, e)  # ✅ 最低でも記録。継続できないなら伝播させる
```

### パターン: `raise ... from` で原因の連鎖を保つ

```python
except KeyError as e:
    raise ClassifyError(f"未知のカテゴリ: {name}") from e  # ✅ 根本原因が辿れる
```

### パターン: 失敗の理由を型で表現する（曖昧な None を返さない）

```python
# ❌ Anti-pattern: None が「未検出」か「デコード失敗」か伝わらない
def load_snippet(relpath: str, lineno: int) -> str | None: ...

# ✅ Pattern: タグ付き union で状態を明示し、呼び出し側は match で網羅処理
@dataclass(frozen=True)
class SnippetFound:
    text: str

@dataclass(frozen=True)
class SnippetNotFound: ...

@dataclass(frozen=True)
class SnippetDecodeError:
    cause: str

SnippetResult = SnippetFound | SnippetNotFound | SnippetDecodeError

match load_snippet(relpath, lineno):
    case SnippetFound(text): ...
    case SnippetNotFound(): ...
    case SnippetDecodeError(cause): ...
```

単純な成功/失敗の2値で足りるなら例外送出のままでよい。失敗の**種類**を呼び出し側で
区別して処理したい場合にのみ結果型を導入する。同類の関数間で表現（例外 / None /
結果型）を混在させないこと。

---

## よくある「やりすぎ」パターン

### 不要なラッパークラス

```python
# ❌ やりすぎ: list を包むだけでロジックが無い — list[Hit] で十分
class HitList:
    def __init__(self, hits: list[Hit]) -> None:
        self._hits = hits
    def get_all(self) -> list[Hit]:
        return self._hits
```

削除テストで判定する: このクラスを消して呼び出し側に `list[Hit]` を展開しても
複雑さが増えないなら、それは通過点（pass-through）であり消してよい。

### 全てを Protocol 化する

実装が1つで差し替え要件が無いものに Protocol を切らない（前掲の導入判断基準を満たす場合のみ）。

### 全てを private 化する

```python
# ❌ やりすぎ: モジュール跨ぎで共有される helper まで _ を付ける
def _file_meta(relpath: str) -> FileMeta: ...   # 他モジュールが import している

# ✅ 共有 helper は public 名のまま（coding-conventions の規約）
def file_meta(relpath: str) -> FileMeta: ...
```

### NewType の乱発

一度しか登場しない引数や、取り違えの現実的リスクが無い値まで NewType に包まない。
型の数が増えるほど読み手の学習コストは上がる。「取り違えバグが実際に起こり得るか」で判断する。
