"""走査中のソース消失（TOCTOU）で run を落とさず欠落降格する仕様。

direct 経路（pipeline）は捕捉済みで、seed/finalize 経路も同じ降格契約に揃える。
外部 I/O 境界（read_bytes_with_sig）のみ test double で失敗を注入する。
"""
from pathlib import Path

import pytest

from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint
from grep_analyzer.fixedpoint._seed import initialize_state
from grep_analyzer.model import Hit


def _opts(**kw):
    base = dict(max_depth=5, min_specificity=2, stoplist_path=None, lang_map={},
                include=[], exclude=[], jobs=1, follow_symlinks=False,
                max_file_bytes=1_000_000, max_symbols=1000, max_paths=100,
                memory_limit_mb=None, use_ripgrep=False, max_passes=8,
                progress="off", spill_dir=None, force_chunks=0)
    base.update(kw)
    return EngineOptions(**base)


def _seed_hit(keyword, language, relpath, lineno, content):
    return Hit(keyword=keyword, language=language, file=relpath, lineno=lineno,
               ref_kind="direct", category="宣言", category_sub="",
               usage_summary=f"宣言 ({language})", via_symbol="",
               chain=f"{keyword}@{relpath}:{lineno}", snippet=content,
               encoding="utf-8", confidence="high")


def _mk(tmp_path, files):
    src = tmp_path / "src"
    src.mkdir()
    for relpath, body in files.items():
        f = src / relpath
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, "utf-8")
    return src


def test_seed読込のOSErrorはrunを落とさず欠落降格し診断に残す(tmp_path, monkeypatch):
    src = _mk(tmp_path, {"C.java": "class C { static final int K = 1; }\n"})

    def _raise(path):
        raise OSError("simulated vanish")

    import grep_analyzer.fixedpoint._seed as seed_mod
    monkeypatch.setattr(seed_mod, "read_bytes_with_sig", _raise)
    diag = Diagnostics()
    seed = _seed_hit("K", "java", "C.java", 1, "static final int K = 1;")
    state = initialize_state([seed], src, _opts(), diag)
    # 消えたファイルの seed は空抽出で ingest され、run は続行できる。
    assert state.keyword == "K"
    assert diag.counts().get("source_read_failed", 0) == 1


def test_finalize再読込のOSErrorはrunを落とさず該当行を空文脈で出力する(tmp_path, monkeypatch):
    src = _mk(tmp_path, {"C.java": 'class C { static final String S_OK = "x"; }\n',
                         "U.java": "class U { String y = S_OK; }\n"})
    seed = _seed_hit("S_OK", "java", "C.java", 1, 'static final String S_OK = "x";')

    import grep_analyzer.fixedpoint._finalize as fin_mod
    real_read = fin_mod.read_bytes_with_sig
    calls = {"n": 0}

    def _flaky(path):
        # finalize 段の再読込だけを消失させる（scan 段は本物の FS を使う）。
        calls["n"] += 1
        raise OSError("simulated vanish")

    monkeypatch.setattr(fin_mod, "read_bytes_with_sig", _flaky)
    diag = Diagnostics()
    hits = run_fixedpoint([seed], src, _opts(max_depth=1), diag)
    # クラッシュせず、U.java の indirect 行は空文脈（snippet 空相当）で残る。
    assert calls["n"] >= 1
    u = [h for h in hits if h.file == "U.java"]
    assert u and u[0].ref_kind == "indirect:constant"
    assert diag.counts().get("source_read_failed", 0) >= 1


def test_finalizeのファイルキャッシュは予算超過で退避しても出力不変(tmp_path, monkeypatch):
    src = _mk(tmp_path, {"C.java": 'class C { static final String T_OK = "x"; }\n',
                         "U.java": "class U { String y = T_OK; }\n",
                         "V.java": "class V { String z = T_OK; }\n"})
    seed = _seed_hit("T_OK", "java", "C.java", 1, 'static final String T_OK = "x";')
    baseline = run_fixedpoint([seed], src, _opts(max_depth=1), Diagnostics())

    import grep_analyzer.fixedpoint._finalize as fin_mod
    monkeypatch.setattr(fin_mod, "_FINALIZE_TEXT_BUDGET", 1)   # 常時退避を強制
    capped = run_fixedpoint([seed], src, _opts(max_depth=1), Diagnostics())
    assert capped == baseline
