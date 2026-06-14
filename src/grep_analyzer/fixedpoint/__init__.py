"""不動点・ターゲットスキャン・エンジンを提供する。

direct ヒットを seed に constant/var を多ホップ追跡し indirect ヒットと chain を出す。
getter/setter は横展開せず全件 low で報告する。
来歴エッジは introducers（実抽出元 Occurrence 群）に基づく（偽 chain 根治）。
出力は走査順・並列完了順に非依存で決定的である。

停止性: 追跡シンボルは原ソース字句のみなので母集合は有限である。
chase_done から削らない（cap は state.capped で scan 除外のみ）ので採用集合は増える一方である。
高々 |母集合| ステップで飽和する。--max-depth/max_symbols/max_paths は安全弁である。
"""

from pathlib import Path

from grep_analyzer import walk
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.fixedpoint._encmemo import EncMemo
from grep_analyzer.fixedpoint._lockstep import run_fixedpoint_multi
from grep_analyzer.fixedpoint._options import EngineOptions
from grep_analyzer.fixedpoint._seed import initialize_state
from grep_analyzer.model import Hit

__all__ = ["EngineOptions", "run_fixedpoint", "run_fixedpoint_multi"]


def run_fixedpoint(
    seed_hits: list[Hit], source_root: Path, opts: EngineOptions, diag: Diagnostics,
    *, files=None, unsafe_rels=None, enc_memo=None
) -> list[Hit]:
    """seed から不動点まで多ホップ追跡し indirect Hit を決定的に返す。

    files 指定時は内部 walk を省き事前収集 (relpath, abspath) 列を使う（同値）。

    unsafe_rels は非ASCII透過（UTF-16/32 BOM 等）ファイルの relpath 集合で、prefilter
    ON 時も常に走査対象に残す（rg は生バイトの ASCII symbol を見つけられず脱落させるため）。
    files=None（内部 walk フォールバック）の場合は unsafe_rels 保護を適用しない
    ＝この経路は直接呼ぶテスト向けである。本番 pipeline は常に files と unsafe_rels の両方を渡す。
    """
    if files is None and unsafe_rels:
        raise ValueError(
            "unsafe_rels は files と併用必須（files=None の walk フォールバックは unsafe 保護を適用しない）")
    source_root = Path(source_root)
    if enc_memo is None:
        enc_memo = EncMemo()                  # 後方互換の内部既定とする（run 共有 enc-memo）
    # seed 初期化の復号も run 共有 enc-memo を通す（同一ファイルの再 chardet を抑止）。
    state = initialize_state(seed_hits, source_root, opts, diag, enc_memo=enc_memo)

    if files is None:
        files = list(walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag))

    # ループは lock-step 共有エンジンへ委譲する（単一 keyword は byte 同値）。
    # rel_to_abs / enc_memo / Progress / automaton_split は run_fixedpoint_multi 側で駆動する。
    result = run_fixedpoint_multi(
        {state.keyword: state}, source_root, opts,
        files=files, unsafe_rels=unsafe_rels, enc_memo=enc_memo)
    return result[state.keyword]
