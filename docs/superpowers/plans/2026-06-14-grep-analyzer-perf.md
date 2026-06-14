# grep_analyzer 60GB 高速化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** decode/言語判定をファイル(mtime/size)単位で run・worker・run跨ぎに1回へ固定する永続デコードキャッシュを中心に、出力バイト不変のまま 60GB 走査を高速化する。

**Architecture:** disk 上の content-addressed ストア `DecodeCache` を新設し、`_read_meta`/`_seed`/`_finalize` の全 decode 経路から参照する。worker はファイルシステム共有のため affinity 不要。加えて `pool.map` の chunksize 指定、大物除外の可視化、opt-in の `--fast-encoding`/`--no-perkw-diag` を足す。

**Tech Stack:** Python 3.12, pytest, multiprocessing.Pool, tree-sitter, 同梱 ripgrep。

参照 spec: `docs/superpowers/specs/2026-06-14-grep-analyzer-perf-design.md`

**全体の不変条件（各タスクの受け入れ条件）:** 既定（フラグOFF）で既存テストが無改変で通る。実行: `pytest -q`。

---

## Task 1: `DecodeCache` モジュール（永続デコードキャッシュ本体）

**Files:**
- Create: `src/grep_analyzer/decode_cache.py`
- Test: `tests/unit/test_decode_cache.py`

値は `(text, enc, replaced, language, dialect)` の 5-tuple（`_meta_from_text` の返り値と同型）。
キーは `(abspath, st_mtime_ns, st_size, namespace)`。アーティファクトは 1 ファイル＝
「1行 JSON ヘッダ ＋ 改行 ＋ 復号UTF-8本文」。本文は valid Unicode（decode_bytes は strict か
replace で必ず valid str を返す）なので utf-8 strict で安全。

- [ ] **Step 1: 失敗するテストを書く（put→get 往復）**

```python
# tests/unit/test_decode_cache.py
from pathlib import Path

from grep_analyzer.decode_cache import DecodeCache


def _src(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_put_then_get_roundtrip(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "a.c", b"int main(){}\n")
    meta = ("int main(){}\n", "utf-8", False, "c", "bourne")
    cache.put(str(src), meta)
    assert cache.get(str(src)) == meta


def test_get_miss_returns_none(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "a.c", b"x\n")
    assert cache.get(str(src)) is None
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_decode_cache.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'grep_analyzer.decode_cache'`）

- [ ] **Step 3: 最小実装**

```python
# src/grep_analyzer/decode_cache.py
"""decode/言語判定の永続キャッシュ。値は (text, enc, replaced, language, dialect)。

キーに (abspath, mtime_ns, size, namespace) を含むため hop・worker・run を
またいで安全に共有でき、ソース変更時は自動でミスする。アーティファクトは
disk 上の 1 ファイル（1行 JSON ヘッダ ＋ 改行 ＋ 復号UTF-8本文）。
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path


class DecodeCache:
    def __init__(self, cache_dir: "Path | None", namespace: str = "") -> None:
        self._dir = Path(cache_dir) if cache_dir is not None \
            else Path(tempfile.mkdtemp(prefix="ga_decode_"))
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ns = namespace

    def _stat(self, abspath: str):
        try:
            st = os.stat(abspath)
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def _artifact_path(self, abspath: str, sig) -> Path:
        mtime_ns, size = sig
        key = f"{self._ns}\0{abspath}\0{mtime_ns}\0{size}"
        h = hashlib.sha1(key.encode("utf-8", "surrogatepass")).hexdigest()
        return self._dir / f"{h}.dca"

    def get(self, abspath: str):
        sig = self._stat(abspath)
        if sig is None:
            return None
        path = self._artifact_path(abspath, sig)
        try:
            with open(path, encoding="utf-8") as f:
                header = f.readline()
                body = f.read()
        except OSError:
            return None
        try:
            meta = json.loads(header)
        except ValueError:
            return None
        if meta.get("mtime_ns") != sig[0] or meta.get("size") != sig[1]:
            return None                       # 防御: stale/衝突
        return (body, meta["enc"], meta["replaced"],
                meta["language"], meta["dialect"])

    def put(self, abspath: str, meta) -> None:
        sig = self._stat(abspath)
        if sig is None:
            return                            # 消えた等は黙ってスキップ（次回再計算）
        text, enc, replaced, language, dialect = meta
        header = json.dumps({
            "enc": enc, "replaced": replaced, "language": language,
            "dialect": dialect, "mtime_ns": sig[0], "size": sig[1],
        }, ensure_ascii=False)
        path = self._artifact_path(abspath, sig)
        fd, tmp = tempfile.mkstemp(dir=str(self._dir), prefix="ga_dca_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(header + "\n")
                f.write(text)
            os.replace(tmp, path)             # 原子的差し替え
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
```

- [ ] **Step 4: テスト成功を確認**

Run: `pytest tests/unit/test_decode_cache.py -q`
Expected: PASS（2 件）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/decode_cache.py tests/unit/test_decode_cache.py
git commit -m "feat(decode_cache): 永続デコードキャッシュの最小put/get"
```

---

## Task 2: `DecodeCache` の無効化・原子性・本文含改行・並列 idempotency

**Files:**
- Test: `tests/unit/test_decode_cache.py`
- Modify: `src/grep_analyzer/decode_cache.py`（必要時のみ。Task1 実装で通る想定）

- [ ] **Step 1: 失敗しうる追加テストを書く**

```python
def test_invalidated_on_mtime_change(tmp_path):
    import os
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "a.c", b"old\n")
    cache.put(str(src), ("OLD", "utf-8", False, "c", "bourne"))
    assert cache.get(str(src)) == ("OLD", "utf-8", False, "c", "bourne")
    # mtime/size を変える（内容変更）→ ミスする
    src.write_bytes(b"newcontent\n")
    os.utime(str(src), ns=(2_000_000_000, 2_000_000_000))
    assert cache.get(str(src)) is None


def test_body_with_newlines_roundtrips(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "b.sql", b"a\nb\nc\n")
    meta = ("行1\n行2\n末尾なし", "cp932", True, "sql", "bourne")
    cache.put(str(src), meta)
    assert cache.get(str(src)) == meta


def test_missing_source_put_is_noop(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    cache.put(str(tmp_path / "does_not_exist"), ("X", "utf-8", False, "c", "bourne"))
    assert cache.get(str(tmp_path / "does_not_exist")) is None
```

- [ ] **Step 2: 実行して確認**

Run: `pytest tests/unit/test_decode_cache.py -q`
Expected: PASS（5 件）。FAIL する場合のみ `decode_cache.py` を修正（本文の改行は `f.read()` で全取得済みなので通る想定）。

- [ ] **Step 3: 並列 idempotency テスト（同一キーへの多重 put）**

```python
def test_concurrent_puts_idempotent(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "c.c", b"same\n")
    meta = ("same\n", "utf-8", False, "c", "bourne")
    for _ in range(20):                       # 同一内容の多重 put は壊れない
        cache.put(str(src), meta)
    assert cache.get(str(src)) == meta
```

- [ ] **Step 4: 実行して確認**

Run: `pytest tests/unit/test_decode_cache.py -q`
Expected: PASS（6 件）

- [ ] **Step 5: コミット**

```bash
git add tests/unit/test_decode_cache.py src/grep_analyzer/decode_cache.py
git commit -m "test(decode_cache): 無効化/改行/欠落/並列idempotencyを固定"
```

---

## Task 3: `_read_meta` を DecodeCache 経由にする（jobs=1 経路）

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_scan.py`（`_read_meta` 署名と本体、`_scan_one`、`scan_hop` の jobs=1 分岐）
- Test: `tests/unit/test_scan_worker.py`（既存ファイルに追加）

`_read_meta` に `decode_cache=None` を追加。階層は L1=in-memory `cache`、L2=`decode_cache`(disk)、
miss=read+decode+detect→両層 put。

- [ ] **Step 1: 失敗するテストを書く（decode_cache hit で再 decode しない）**

```python
# tests/unit/test_scan_worker.py に追加
def test_read_meta_uses_decode_cache(tmp_path, monkeypatch):
    from grep_analyzer.fixedpoint import _scan
    from grep_analyzer.decode_cache import DecodeCache

    src = tmp_path / "a.c"
    src.write_bytes(b"int x;\n")
    dc = DecodeCache(tmp_path / "cache")
    meta = ("int x;\n", "utf-8", False, "c", "bourne")
    dc.put(str(src), meta)

    calls = {"n": 0}
    real = _scan.decode_bytes
    def spy(data, chain):
        calls["n"] += 1
        return real(data, chain)
    monkeypatch.setattr(_scan, "decode_bytes", spy)

    got = _scan._read_meta("a.c", str(src), {}, ["cp932"], None, decode_cache=dc)
    assert got == meta
    assert calls["n"] == 0                     # disk hit ＝ decode 未実行
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_scan_worker.py::test_read_meta_uses_decode_cache -q`
Expected: FAIL（`_read_meta() got an unexpected keyword argument 'decode_cache'`）

- [ ] **Step 3: `_read_meta` を実装変更**

`src/grep_analyzer/fixedpoint/_scan.py` の `_read_meta` を次に置換:

```python
def _read_meta(relpath, abspath, lang_map, fallback, cache, enc_memo=None,
               decode_cache=None):
    """file_meta 結果を階層キャッシュ経由で取得。

    L1=in-memory(cache) → L2=disk(decode_cache) → miss=read+decode+detect。
    decode_cache は hop・worker・run をまたいで decode/言語判定を 1 回に固定する。
    """
    if cache is not None:
        hit = cache.get(abspath)
        if hit is not None:
            return hit
    if decode_cache is not None:
        dhit = decode_cache.get(abspath)
        if dhit is not None:
            if cache is not None:
                cache.put(abspath, dhit)
            return dhit
    raw = Path(abspath).read_bytes()
    if enc_memo is None:
        meta = file_meta(relpath, raw, lang_map, fallback_chain=fallback)
    else:
        meta = meta_via_memo(enc_memo, abspath, relpath, raw, lang_map, fallback)
    if decode_cache is not None:
        decode_cache.put(abspath, meta)
    if cache is not None:
        cache.put(abspath, meta)
    return meta
```

`_scan_one` の署名に `decode_cache=None` を足し、`_read_meta(...)` 呼出に渡す:

```python
def _scan_one(relpath, abspath, automaton_obj, lang_map, fallback, cache=None,
              enc_memo=None, decode_cache=None):
    ...
        text, enc, replaced, language, dialect = _read_meta(
            relpath, abspath, lang_map, fallback, cache, enc_memo, decode_cache)
```

`scan_hop` の署名に `decode_cache=None` を足し、jobs<=1 分岐の `_scan_one(...)` に渡す:

```python
def scan_hop(scan_symbols, scan_files, opts, nchunks, file_cache=None, pool=None,
             enc_memo=None, decode_cache=None):
    ...
        else:
            automaton_obj = automaton.build(chunk)
            res = [_scan_one(relpath, str(abspath), automaton_obj,
                             opts.lang_map, fallback,
                             cache=file_cache, enc_memo=enc_memo,
                             decode_cache=decode_cache)
                   for relpath, abspath in scan_files]
```

- [ ] **Step 4: テスト成功を確認**

Run: `pytest tests/unit/test_scan_worker.py::test_read_meta_uses_decode_cache -q`
Expected: PASS

- [ ] **Step 5: 既存 scan テストの非回帰**

Run: `pytest tests/unit/test_scan_worker.py tests/unit/test_pipeline.py -q`
Expected: PASS（全件）

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/fixedpoint/_scan.py tests/unit/test_scan_worker.py
git commit -m "feat(scan): _read_meta を DecodeCache L2 経由に（jobs=1）"
```

---

## Task 4: worker への DecodeCache 配線（jobs>1）＋ run 単位生成

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_scan.py`（`_worker_init`, `_scan_file_worker`, `make_pool`, `make_decode_cache` 追加）
- Modify: `src/grep_analyzer/fixedpoint/_lockstep.py`（run 単位生成・`scan_hop` へ伝播）
- Modify: `src/grep_analyzer/fixedpoint/_options.py`（`decode_cache_dir` 追加）
- Test: `tests/unit/test_dispatch.py` または `tests/unit/test_lockstep_interrupt.py`（jobs>1 経路の薄い確認）

worker はファイルシステム共有なので、同一 `decode_cache_dir` を指す `DecodeCache` を各 worker が
自前生成すれば affinity 不要で decode が 1 回に収束する。

- [ ] **Step 1: `EngineOptions` に項目追加**

`src/grep_analyzer/fixedpoint/_options.py` の dataclass に追記:

```python
    decode_cache_dir: Path | None = None
```

- [ ] **Step 2: `make_decode_cache` と worker グローバルを追加**

`src/grep_analyzer/fixedpoint/_scan.py`:

```python
from grep_analyzer.decode_cache import DecodeCache

_WORKER_DECODE_CACHE: "DecodeCache | None" = None


def make_decode_cache(opts, namespace: str = ""):
    """run 単位の永続デコードキャッシュ。decode_cache_dir 無指定なら run 専用 temp。"""
    return DecodeCache(opts.decode_cache_dir, namespace=namespace)
```

`_worker_init` を拡張（initargs に cache_dir, namespace を追加）:

```python
def _worker_init(lang_map, fallback, jobs, decode_cache_dir, namespace) -> None:
    global _WORKER_LANG_MAP, _WORKER_FALLBACK, _WORKER_CACHE, _WORKER_SIG, _WORKER_AUTOMATON
    global _WORKER_ENC, _WORKER_DECODE_CACHE
    _WORKER_LANG_MAP = lang_map
    _WORKER_FALLBACK = fallback
    _WORKER_CACHE = _FileCache(budget=_FILE_CACHE_BUDGET // max(1, jobs))
    _WORKER_ENC = EncMemo(max_entries=max(1, _ENC_MEMO_MAX // max(1, jobs)))
    _WORKER_SIG = None
    _WORKER_AUTOMATON = None
    _WORKER_DECODE_CACHE = DecodeCache(decode_cache_dir, namespace=namespace)
```

`_scan_file_worker` で渡す:

```python
    return _scan_one(relpath, abspath, _WORKER_AUTOMATON,
                     _WORKER_LANG_MAP, _WORKER_FALLBACK,
                     cache=_WORKER_CACHE, enc_memo=_WORKER_ENC,
                     decode_cache=_WORKER_DECODE_CACHE)
```

`make_pool` を拡張（namespace 引数を受け、initargs を更新）:

```python
def make_pool(opts, namespace: str = ""):
    if opts.jobs <= 1:
        return None
    return multiprocessing.Pool(
        opts.jobs, initializer=_worker_init,
        initargs=(opts.lang_map, list(opts.encoding_fallback), opts.jobs,
                  opts.decode_cache_dir, namespace))
```

- [ ] **Step 3: `_lockstep.py` で run 単位生成し伝播**

`run_fixedpoint_multi` 内、`file_cache = make_file_cache()` の直後:

```python
    from grep_analyzer.fixedpoint._scan import make_decode_cache
    decode_cache = make_decode_cache(opts)
    file_cache = make_file_cache()
    pool = make_pool(opts)
```

`scan_hop(...)` 呼出に `decode_cache=decode_cache` を追加:

```python
            pass_results, n_actual_chunks = scan_hop(
                scan_symbols, scan_files, opts, nchunks,
                file_cache=file_cache, pool=pool, enc_memo=enc_memo,
                decode_cache=decode_cache)
```

- [ ] **Step 4: jobs=1 / jobs>1 で出力一致テスト**

```python
# tests/unit/test_decode_cache_integration.py（新規）
from pathlib import Path

from grep_analyzer.pipeline import run
from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.walk import DEFAULT_EXCLUDE


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "a.c").write_bytes("int foo;\nint bar;\n".encode("cp932"))
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "foo.grep").write_bytes(f"{src/'a.c'}:1:int foo;\n".encode())
    return src, inp


def test_jobs1_vs_jobs2_identical_with_decode_cache(tmp_path):
    src, inp = _setup(tmp_path)
    out1 = tmp_path / "o1"; out2 = tmp_path / "o2"
    base = dict(exclude=list(DEFAULT_EXCLUDE),
                decode_cache_dir=tmp_path / "dc1")
    run(inp, out1, src, EngineOptions(jobs=1, **base))
    base2 = dict(exclude=list(DEFAULT_EXCLUDE),
                 decode_cache_dir=tmp_path / "dc2")
    run(inp, out2, src, EngineOptions(jobs=2, **base2))
    a = sorted(p.name for p in out1.glob("*.tsv"))
    b = sorted(p.name for p in out2.glob("*.tsv"))
    assert a == b
    for name in a:
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()
```

- [ ] **Step 5: 実行して確認**

Run: `pytest tests/unit/test_decode_cache_integration.py -q && pytest -q`
Expected: PASS（新規＋全既存）

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/fixedpoint/_scan.py src/grep_analyzer/fixedpoint/_lockstep.py src/grep_analyzer/fixedpoint/_options.py tests/unit/test_decode_cache_integration.py
git commit -m "feat(scan): worker跨ぎDecodeCache配線＋run単位生成（jobs>1出力一致）"
```

---

## Task 5: `_seed` / `_finalize` の decode も DecodeCache 経由にする

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_scan.py`（`meta_via_memo` に decode_cache 対応の薄いラッパ `meta_cached` を追加）
- Modify: `src/grep_analyzer/fixedpoint/_seed.py`（`initialize_state` に `decode_cache` 引数、seed decode を経由）
- Modify: `src/grep_analyzer/fixedpoint/_finalize.py`（`build_indirect_hits` の decode を経由）
- Modify: `src/grep_analyzer/fixedpoint/_lockstep.py` / `src/grep_analyzer/pipeline.py`（decode_cache を seed/finalize に渡す）
- Test: `tests/unit/test_seed_finalize_decode_cache.py`（新規）

seed/finalize は `meta_via_memo`/`file_meta` を直呼びしている。decode_cache hit を優先する
共通ヘルパ `meta_cached` を追加して両者から使う（出力は同一経路の純再生＝不変）。

- [ ] **Step 1: 失敗するテスト（seed が decode_cache hit を使う）**

```python
# tests/unit/test_seed_finalize_decode_cache.py
from pathlib import Path

from grep_analyzer.decode_cache import DecodeCache
from grep_analyzer.fixedpoint import _scan


def test_meta_cached_prefers_decode_cache(tmp_path, monkeypatch):
    src = tmp_path / "a.c"
    src.write_bytes(b"int x;\n")
    dc = DecodeCache(tmp_path / "cache")
    meta = ("int x;\n", "utf-8", False, "c", "bourne")
    dc.put(str(src), meta)

    calls = {"n": 0}
    real = _scan.decode_bytes
    monkeypatch.setattr(_scan, "decode_bytes",
                        lambda d, c: (calls.__setitem__("n", calls["n"] + 1), real(d, c))[1])

    got = _scan.meta_cached(None, dc, str(src), "a.c", src.read_bytes(), {}, ["cp932"])
    assert got == meta
    assert calls["n"] == 0
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_seed_finalize_decode_cache.py -q`
Expected: FAIL（`module 'grep_analyzer.fixedpoint._scan' has no attribute 'meta_cached'`）

- [ ] **Step 3: `meta_cached` を実装**

`src/grep_analyzer/fixedpoint/_scan.py` に追加:

```python
def meta_cached(enc_memo, decode_cache, key, relpath, raw, lang_map, fallback):
    """decode_cache hit を優先し、miss は meta_via_memo/file_meta と同一結果を put して返す。

    seed/finalize の直呼び decode を hop 走査と同じ永続層に乗せる。出力同値。
    """
    if decode_cache is not None:
        dhit = decode_cache.get(key)
        if dhit is not None:
            return dhit
    if enc_memo is not None:
        meta = meta_via_memo(enc_memo, key, relpath, raw, lang_map, fallback)
    else:
        meta = file_meta(relpath, raw, lang_map, fallback_chain=fallback)
    if decode_cache is not None:
        decode_cache.put(key, meta)
    return meta
```

- [ ] **Step 4: テスト成功を確認**

Run: `pytest tests/unit/test_seed_finalize_decode_cache.py -q`
Expected: PASS

- [ ] **Step 5: seed/finalize を `meta_cached` 経由に切替**

`_seed.py`: `initialize_state(..., enc_memo=None, decode_cache=None)` を追加し、seed decode 部を:

```python
                cur_text, _, _, cur_lang, cur_dialect = meta_cached(
                    enc_memo, decode_cache, str(sp), s.file, sp.read_bytes(),
                    opts.lang_map, list(opts.encoding_fallback))
```
（import を `from grep_analyzer.fixedpoint._scan import kinds_of, meta_cached` に変更。enc_memo 分岐は撤去）

`_finalize.py`: `build_indirect_hits` の abspath あり分岐を:

```python
                text, enc, replaced, lang, dialect = meta_cached(
                    state.enc_memo, state.decode_cache, str(abspath), c.relpath, raw,
                    opts.lang_map, list(opts.encoding_fallback))
```
（import に `meta_cached` 追加。`ChaseState` に `decode_cache=None` フィールドを足す＝`_state.py` 修正）

`_lockstep.py`: `for st in states_by_kw.values(): st.enc_memo = enc_memo` の隣で
`st.decode_cache = decode_cache` も設定。`pipeline.py` の `initialize_state(...)` 呼出に
`decode_cache=decode_cache` を渡す（pipeline で run 単位の decode_cache を 1 つ作り、
`run_fixedpoint_multi` にも同一インスタンスを渡すよう引数追加）。

- [ ] **Step 6: 非回帰（golden 含む）**

Run: `pytest -q`
Expected: PASS（全件・golden 無改変）

- [ ] **Step 7: コミット**

```bash
git add src/grep_analyzer/fixedpoint/_scan.py src/grep_analyzer/fixedpoint/_seed.py src/grep_analyzer/fixedpoint/_finalize.py src/grep_analyzer/fixedpoint/_state.py src/grep_analyzer/fixedpoint/_lockstep.py src/grep_analyzer/pipeline.py tests/unit/test_seed_finalize_decode_cache.py
git commit -m "feat: seed/finalize の decode も DecodeCache 経由（decode 1回化を全経路へ）"
```

---

## Task 6: DecodeCache の生成元一本化と cleanup（pipeline で run 単位生成）

**Files:**
- Modify: `src/grep_analyzer/pipeline.py`（run 単位 decode_cache 生成、`run_fixedpoint_multi`/`initialize_state` へ共有）
- Modify: `src/grep_analyzer/fixedpoint/_lockstep.py`（`run_fixedpoint_multi(..., decode_cache=None)` 受け取り）
- Test: `tests/unit/test_pipeline.py`（decode_cache_dir 指定時の再利用を 1 件追加）

run 内で複数箇所が別々に decode_cache を作ると namespace/dir がズレる。pipeline で 1 度だけ作って
共有する。Task4 の `make_decode_cache(opts)` 呼出を `run_fixedpoint_multi` 内から pipeline 側へ移動。

- [ ] **Step 1: run 跨ぎ再利用テスト（2回目は decode 0 回）**

```python
# tests/unit/test_pipeline.py に追加
def test_decode_cache_dir_reused_across_runs(tmp_path, monkeypatch):
    from grep_analyzer.pipeline import run
    from grep_analyzer.fixedpoint import EngineOptions
    from grep_analyzer.walk import DEFAULT_EXCLUDE
    from grep_analyzer.fixedpoint import _scan

    src = tmp_path / "src"; src.mkdir()
    (src / "a.c").write_bytes("int foo;\n".encode("cp932"))
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "foo.grep").write_bytes(f"{src/'a.c'}:1:int foo;\n".encode())
    dc_dir = tmp_path / "dc"
    opts = lambda o: EngineOptions(jobs=1, exclude=list(DEFAULT_EXCLUDE),
                                   decode_cache_dir=dc_dir)
    run(inp, tmp_path / "o1", src, opts(None))      # 1 回目: ストア充填

    calls = {"n": 0}
    real = _scan.decode_bytes
    monkeypatch.setattr(_scan, "decode_bytes",
                        lambda d, c: (calls.__setitem__("n", calls["n"] + 1), real(d, c))[1])
    run(inp, tmp_path / "o2", src, opts(None))      # 2 回目: 全 hit
    assert calls["n"] == 0
```

- [ ] **Step 2: 実行（まだ FAIL しうる＝生成元が分散していると 2 回目も decode する）**

Run: `pytest tests/unit/test_pipeline.py::test_decode_cache_dir_reused_across_runs -q`
Expected: 最初は FAIL（decode が呼ばれる）。生成元一本化で PASS にする。

- [ ] **Step 3: pipeline で 1 度だけ生成し共有**

`pipeline.py` の `run()` 内、`enc_memo = EncMemo()` の隣:

```python
    from grep_analyzer.fixedpoint._scan import make_decode_cache
    decode_cache = make_decode_cache(opts)
```
`initialize_state(...)` に `decode_cache=decode_cache`、`run_fixedpoint_multi(...)` に
`decode_cache=decode_cache` を渡す。`_lockstep.run_fixedpoint_multi` は引数で受け取り、
内部生成（Task4 の `make_decode_cache`）を削除して受領インスタンスを使う。

- [ ] **Step 4: テスト成功＋全体非回帰**

Run: `pytest -q`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/pipeline.py src/grep_analyzer/fixedpoint/_lockstep.py tests/unit/test_pipeline.py
git commit -m "refactor: DecodeCache を run 単位で一本生成・全経路共有（run跨ぎ再利用）"
```

---

## Task 7: CLI `--decode-cache-dir`

**Files:**
- Modify: `src/grep_analyzer/cli.py`（引数追加と `_opts_from` 反映）
- Test: `tests/unit/test_cli_validation.py` または `test_cli_phase3.py`（1 件）

- [ ] **Step 1: 失敗するテスト**

```python
def test_decode_cache_dir_parsed(tmp_path):
    from grep_analyzer.cli import _build_opts
    opts = _build_opts(["--input", str(tmp_path), "--output", str(tmp_path),
                        "--source-root", str(tmp_path),
                        "--decode-cache-dir", str(tmp_path / "dc")])
    assert str(opts.decode_cache_dir).endswith("dc")
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_cli_phase3.py::test_decode_cache_dir_parsed -q`
Expected: FAIL（属性 None / 引数未知）

- [ ] **Step 3: CLI に追加**

`_make_parser` に:

```python
    parser.add_argument("--decode-cache-dir", default=None, dest="decode_cache_dir",
                        help="復号/言語判定の永続キャッシュ置き場（run跨ぎ再利用可。無指定はrun専用temp）")
```
`_opts_from` の `EngineOptions(...)` に:

```python
        decode_cache_dir=Path(args.decode_cache_dir) if args.decode_cache_dir else None,
```

- [ ] **Step 4: テスト成功＋CLI help 非回帰**

Run: `pytest tests/unit/test_cli_phase3.py::test_decode_cache_dir_parsed tests/unit/test_cli_help.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/cli.py tests/unit/test_cli_phase3.py
git commit -m "feat(cli): --decode-cache-dir"
```

---

## Task 8: `pool.map` の chunksize 指定（jobs>1 スケーリング）

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_scan.py`（`scan_hop` の `pool.map` に決定的 chunksize）
- Test: `tests/unit/test_scan_worker.py`（chunksize 算出のユニット）

chunksize は順序保存に無関係（`pool.map` は常に入力順で返す）＝出力不変。決定式で算出。

- [ ] **Step 1: 失敗するテスト（chunksize ヘルパ）**

```python
def test_map_chunksize_is_deterministic_and_positive():
    from grep_analyzer.fixedpoint._scan import _map_chunksize
    assert _map_chunksize(0, 4) == 1
    assert _map_chunksize(1000, 4) >= 1
    assert _map_chunksize(1000, 4) == _map_chunksize(1000, 4)   # 決定的
    # ファイル数が多いほど chunksize は 1 より大きくなる
    assert _map_chunksize(100000, 8) > 1
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_scan_worker.py::test_map_chunksize_is_deterministic_and_positive -q`
Expected: FAIL（`cannot import name '_map_chunksize'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/fixedpoint/_scan.py`:

```python
def _map_chunksize(n_files: int, jobs: int) -> int:
    """pool.map 用の決定的 chunksize（順序保存ゆえ出力不変）。

    既定の chunksize=1 はファイル毎 IPC でディスパッチ過多。worker あたり概ね
    4 バッチに割れる粒度にして round-trip を削減する。
    """
    if n_files <= 0:
        return 1
    return max(1, n_files // (max(1, jobs) * 4))
```
`scan_hop` の `pool.map(_scan_file_worker, [...])` を:

```python
                args = [(relpath, str(abspath), sig, sym_path)
                        for relpath, abspath in scan_files]
                res = pool.map(_scan_file_worker, args,
                               chunksize=_map_chunksize(len(args), opts.jobs))
```

- [ ] **Step 4: テスト成功＋jobs>1 出力一致の非回帰**

Run: `pytest tests/unit/test_scan_worker.py tests/unit/test_decode_cache_integration.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/fixedpoint/_scan.py tests/unit/test_scan_worker.py
git commit -m "perf(scan): pool.map に決定的 chunksize（IPC round-trip 削減・出力不変）"
```

---

## Task 9: 大物ファイル除外の可視化

**Files:**
- Modify: `src/grep_analyzer/pipeline.py`（run 末尾で `walk_skipped_large` 件数を stderr 警告）
- Test: `tests/unit/test_pipeline.py`（>0 件で警告、0 件で無音）

walk は `walk_skipped_large` を walk_diag に積む（`walk.py`）。これを集計し stderr に 1 行出す
（出力TSV・diagnostics.txt は不変、stderr のみ追加）。

- [ ] **Step 1: 失敗するテスト**

```python
def test_large_file_skip_warns_on_stderr(tmp_path, capsys):
    from grep_analyzer.pipeline import run
    from grep_analyzer.fixedpoint import EngineOptions
    from grep_analyzer.walk import DEFAULT_EXCLUDE
    src = tmp_path / "src"; src.mkdir()
    (src / "big.c").write_bytes(b"x" * 50)
    (src / "small.c").write_bytes(b"int foo;\n")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "foo.grep").write_bytes(f"{src/'small.c'}:1:int foo;\n".encode())
    run(inp, tmp_path / "o", src,
        EngineOptions(jobs=1, exclude=list(DEFAULT_EXCLUDE), max_file_bytes=10))
    err = capsys.readouterr().err
    assert "big.c" in err or "skipped" in err.lower() or "除外" in err
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_pipeline.py::test_large_file_skip_warns_on_stderr -q`
Expected: FAIL（stderr に警告なし）

- [ ] **Step 3: 実装**

`pipeline.py` の `run()` 末尾（`return 0` の直前）に:

```python
    import sys
    n_large = walk_diag.counts().get("walk_skipped_large", 0)
    if n_large:
        print(f"[grep_analyzer] 警告: {n_large} 件のファイルが "
              f"--max-file-bytes({opts.max_file_bytes}) 超で除外されました "
              f"（詳細は diagnostics.txt の walk_skipped_large）", file=sys.stderr)
```
注: `Diagnostics` に件数取得 API が無い場合は `diag.counts()` 相当を確認し、無ければ
`walk_diag` の内部件数辞書から取得するヘルパを `diagnostics.py` に足す（`counts() -> dict[str,int]`）。
その場合は `tests/unit/test_diagnostics_phase3.py` に `counts()` の 1 ケースを追加してから実装する。

- [ ] **Step 4: テスト成功＋非回帰**

Run: `pytest tests/unit/test_pipeline.py tests/unit/test_diagnostics_phase3.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/pipeline.py src/grep_analyzer/diagnostics.py tests/unit/test_pipeline.py tests/unit/test_diagnostics_phase3.py
git commit -m "feat: --max-file-bytes 除外を stderr で可視化（出力不変）"
```

---

## Task 10: B-1 `--fast-encoding`（opt-in・全 decode 配線・キャッシュ名前空間分離）

**Files:**
- Modify: `src/grep_analyzer/encoding.py`（`decode_bytes`/`decode_with_memo` に `fast` 追加）
- Modify: `src/grep_analyzer/fixedpoint/_scan.py`（`file_meta`/`meta_via_memo`/`meta_cached` に `fast` 透過、worker initargs、DecodeCache namespace）
- Modify: `src/grep_analyzer/pipeline.py`（直接 decode 2 箇所、decode_cache namespace）
- Modify: `src/grep_analyzer/fixedpoint/_options.py`（`fast_encoding: bool = False`）
- Modify: `src/grep_analyzer/cli.py`（`--fast-encoding`）
- Test: `tests/unit/test_encoding.py`（fast 順序）, `tests/unit/test_decode_cache_integration.py`（fast/非fast 分離）

`fast` は run 全体で定数。DecodeCache namespace に `"fast" if fast else ""` を入れ、fast/非fast の
アーティファクトを分離（同一ファイルが別エンコーディングで保存されても衝突しない）。

- [ ] **Step 1: 失敗するテスト（fast は chardet 前に fallback strict）**

```python
# tests/unit/test_encoding.py に追加
def test_fast_mode_prefers_chain_before_chardet(monkeypatch):
    import grep_analyzer.encoding as enc
    called = {"chardet": 0}
    monkeypatch.setattr(enc.chardet, "detect",
                        lambda d: called.__setitem__("chardet", called["chardet"] + 1) or {"encoding": "euc-jp"})
    data = "テスト".encode("cp932")
    text, used, replaced = enc.decode_bytes(data, ["cp932", "euc-jp", "latin-1"], fast=True)
    assert used == "cp932"
    assert called["chardet"] == 0            # fast: cp932 strict 成功で chardet 未呼出
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_encoding.py::test_fast_mode_prefers_chain_before_chardet -q`
Expected: FAIL（`decode_bytes() got an unexpected keyword argument 'fast'`）

- [ ] **Step 3: `encoding.py` を実装**

```python
def decode_bytes(data, fallback_chain, fast=False):
    try:
        return data.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        pass
    if fast:
        for e in fallback_chain[:-1]:         # chardet 前に鎖 strict を試す
            try:
                return data.decode(e), e, False
            except (UnicodeDecodeError, LookupError):
                continue
    detected = chardet.detect(data).get("encoding")
    if detected:
        try:
            return data.decode(detected), detected.lower(), False
        except (UnicodeDecodeError, LookupError):
            pass
    for enc in fallback_chain[:-1]:
        try:
            return data.decode(enc), enc, False
        except (UnicodeDecodeError, LookupError):
            continue
    last = fallback_chain[-1]
    return data.decode(last, errors="replace"), last, True
```
`decode_with_memo(memo, abspath, data, fallback_chain, fast=False)` に `fast` を足し、miss 時
`decode_bytes(data, fallback_chain, fast=fast)` を呼ぶ。

- [ ] **Step 4: テスト成功を確認**

Run: `pytest tests/unit/test_encoding.py -q`
Expected: PASS

- [ ] **Step 5: `fast` を全 decode 経路へ透過**

`_scan.py`: `file_meta(..., fast=False)`, `meta_via_memo(..., fast=False)`,
`meta_cached(..., fast=False)` に追加し `decode_*` へ渡す。`_read_meta(..., fast=False)`、
`_scan_one(..., fast=False)`、`scan_hop(..., fast=...)`（`opts.fast_encoding` 由来）。
`_worker_init` initargs に `fast` を足し worker 内グローバル `_WORKER_FAST` に保持、
`_scan_file_worker` から `_scan_one(..., fast=_WORKER_FAST)`。
`make_pool(opts, namespace=...)` / `make_decode_cache(opts, namespace=...)` の namespace を
pipeline 側で `"fast" if opts.fast_encoding else ""` にする。
`pipeline.py` の直接 decode（grep ファイル `decode_bytes` と content `decode_with_memo`）にも
`fast=opts.fast_encoding` を渡す。`_options.py` に `fast_encoding: bool = False`。
`cli.py` に `--fast-encoding`（store_true）と `_opts_from` 反映。

- [ ] **Step 6: fast/非fast の DecodeCache 分離テスト＋全体非回帰**

```python
# tests/unit/test_decode_cache_integration.py に追加
def test_fast_and_nonfast_use_separate_namespaces(tmp_path):
    from grep_analyzer.decode_cache import DecodeCache
    src = tmp_path / "a.c"; src.write_bytes(b"x\n")
    a = DecodeCache(tmp_path / "dc", namespace="")
    b = DecodeCache(tmp_path / "dc", namespace="fast")
    a.put(str(src), ("NONFAST", "euc-jp", False, "c", "bourne"))
    b.put(str(src), ("FAST", "cp932", False, "c", "bourne"))
    assert a.get(str(src))[0] == "NONFAST"
    assert b.get(str(src))[0] == "FAST"
```

Run: `pytest -q`
Expected: PASS（全件・既定OFFで golden 不変）

- [ ] **Step 7: コミット**

```bash
git add src/grep_analyzer/encoding.py src/grep_analyzer/fixedpoint/_scan.py src/grep_analyzer/fixedpoint/_options.py src/grep_analyzer/pipeline.py src/grep_analyzer/cli.py tests/unit/test_encoding.py tests/unit/test_decode_cache_integration.py
git commit -m "feat(cli): --fast-encoding（cp932優先短絡・全decode配線・キャッシュ名前空間分離）"
```

---

## Task 11: B-2 `--no-perkw-diag`（opt-in・per-keyword rg 削減）

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_options.py`（`perkw_diag: bool = True`）
- Modify: `src/grep_analyzer/fixedpoint/_lockstep.py`（flag 時 per-keyword 再 prefilter をスキップ）
- Modify: `src/grep_analyzer/cli.py`（`--no-perkw-diag`）
- Test: `tests/unit/test_lockstep_interrupt.py` か新規（per-keyword TSV 不変・診断のみ差）

- [ ] **Step 1: 失敗するテスト（perkw_diag=False でも per-keyword TSV 不変）**

```python
# tests/unit/test_perkw_diag.py（新規）
from pathlib import Path
from grep_analyzer.pipeline import run
from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.walk import DEFAULT_EXCLUDE


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "a.c").write_bytes("int foo; int bar;\n".encode("cp932"))
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "foo.grep").write_bytes(f"{src/'a.c'}:1:int foo; int bar;\n".encode())
    return src, inp


def test_perkw_diag_off_keeps_tsv_identical(tmp_path):
    src, inp = _setup(tmp_path)
    common = dict(jobs=1, exclude=list(DEFAULT_EXCLUDE), use_ripgrep=True)
    run(inp, tmp_path / "on", src, EngineOptions(perkw_diag=True, **common))
    run(inp, tmp_path / "off", src, EngineOptions(perkw_diag=False, **common))
    on = sorted(p.name for p in (tmp_path / "on").glob("*.tsv"))
    off = sorted(p.name for p in (tmp_path / "off").glob("*.tsv"))
    assert on == off
    for name in on:
        assert (tmp_path / "on" / name).read_bytes() == (tmp_path / "off" / name).read_bytes()
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/unit/test_perkw_diag.py -q`
Expected: FAIL（`perkw_diag` 未知）

- [ ] **Step 3: 実装**

`_options.py` に `perkw_diag: bool = True`。
`_lockstep.py` の per-keyword 帰属ループを:

```python
            for kw, st in states_by_kw.items():
                sc, stm = per_kw[kw]
                kw_results = pass_results
                if opts.perkw_diag and opts.use_ripgrep and union_keep is not None:
                    keep_k = _rg.prefilter(source_root, rel_to_abs, sorted(sc | stm),
                                           restrict_to=union_keep)
                    if keep_k is not None:
                        keep_k = keep_k | unsafe_rels
                        kw_results = [r for r in pass_results if r[0] in keep_k]
                absorb_results(st, kw_results, sc, stm, ghop)
```
`cli.py` に `--no-perkw-diag`（`dest="perkw_diag", action="store_false", default=True`）と
`_opts_from` 反映。

- [ ] **Step 4: テスト成功＋全体非回帰**

Run: `pytest tests/unit/test_perkw_diag.py -q && pytest -q`
Expected: PASS（per-keyword TSV byte 一致・全既存）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/fixedpoint/_options.py src/grep_analyzer/fixedpoint/_lockstep.py src/grep_analyzer/cli.py tests/unit/test_perkw_diag.py
git commit -m "feat(cli): --no-perkw-diag（per-keyword rg spawn 削減・TSV不変）"
```

---

## Task 12: 運用ドキュメント（①⑤）

**Files:**
- Modify: `README`（無ければ `docs/PERFORMANCE.md` 新規）
- Test: なし（ドキュメント）

- [ ] **Step 1: 推奨実行例を記載**

60GB 向け推奨:
```
grep_analyzer --jobs <コア数> --decode-cache-dir /var/tmp/ga_cache \
              --input ... --output ... --source-root ... \
              [--max-depth 4] [--exclude <vendor/生成物>] [--resume] [--fast-encoding]
```
各フラグの効果・出力不変/変化の別、`--max-file-bytes` の既定 5MB 除外（大物は落ちる）を明記。

- [ ] **Step 2: コミット**

```bash
git add README docs/PERFORMANCE.md
git commit -m "docs: 60GB 向け推奨実行例とフラグ効果"
```

---

## Self-Review チェック結果

- **Spec coverage:** spec §3.1→Task1-7, §3.2→Task8, §3.3→Task9, §3.4(B-1)→Task10,
  §3.5(B-2)→Task11, §3.4運用→Task12。②はドロップ（spec §6）でタスク無し＝整合。
- **Placeholder scan:** 各コード手順に実コードを記載。Task9 の `counts()` のみ「無ければ足す」
  条件分岐があるが、確認手順とテスト追加を明示済み（実装時に `diagnostics.py` を確認）。
- **Type consistency:** decode meta は全経路 `(text, enc, replaced, language, dialect)` の 5-tuple で統一。
  `DecodeCache.get/put`・`_read_meta`・`meta_cached`・`meta_via_memo`・`file_meta` で同型。
  `decode_cache` 引数名・`namespace` 引数名・`fast` 引数名は全タスクで一貫。
- **既定不変:** Task1-9 は出力不変、Task10-11 は既定OFF。各タスクに `pytest -q` 非回帰ゲートあり。
