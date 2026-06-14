import argparse
from pathlib import Path

from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.pipeline import run
from grep_analyzer.walk import DEFAULT_EXCLUDE


def _parse_lang_map(spec: str | None) -> dict[str, str]:
    """`.ext=lang,.e2=l2` を {".ext":"lang"} に変換する。空は {} を返す（手順1）。"""
    lang_map: dict[str, str] = {}
    if spec:
        for pair in spec.split(","):
            ext, _, lang = pair.partition("=")
            if ext and lang:
                lang_map[ext if ext.startswith(".") else "." + ext] = lang
    return lang_map


def _make_parser() -> argparse.ArgumentParser:
    """共通 ArgumentParser を組み立てて返す。"""
    parser = argparse.ArgumentParser(
        prog="grep_analyzer",
        description="grep 結果を言語別に分類し決定的 TSV を出力する（直接＋不動点で間接参照も追跡）。")
    parser.add_argument("--input", required=True,
                        help="キーワードごとの *.grep（path:lineno:content 行）を置いたディレクトリ")
    parser.add_argument("--output", required=True,
                        help="TSV・manifest・diagnostics.txt の出力先ディレクトリ")
    parser.add_argument("--source-root", required=True, dest="source_root",
                        help="ヒット箇所の実ソースを解決するルート")
    parser.add_argument("--max-depth", type=int, default=10, dest="max_depth",
                        help="不動点の最大 hop 数（既定 10）")
    parser.add_argument("--min-specificity", type=int, default=2, dest="min_specificity",
                        help="追跡する記号の最小文字数（既定 2・短すぎる記号を除外）")
    parser.add_argument("--stoplist", default=None,
                        help="追跡から除外する記号を列挙したファイル")
    parser.add_argument("--lang-map", default=None, dest="lang_map",
                        help="拡張子→言語の上書き（例 .inc=c,.tpl=jsp）")
    parser.add_argument("--include", action="append", default=[],
                        help="走査対象に含める glob（複数指定可）")
    parser.add_argument("--exclude", action="append", default=None,
                        help="走査から除外する glob（複数指定可・既定除外を上書き）")
    parser.add_argument("--jobs", type=int, default=1,
                        help="走査並列度（既定 1。N でも出力はバイト同一）")
    parser.add_argument("--follow-symlinks", action="store_true", dest="follow_symlinks",
                        help="シンボリックリンクをたどる（既定 off）")
    parser.add_argument("--max-file-bytes", type=int, default=5_000_000, dest="max_file_bytes",
                        help="走査対象とするファイルの最大バイト数（既定 5MB）")
    parser.add_argument("--max-symbols", type=int, default=100_000, dest="max_symbols",
                        help="追跡記号数の上限（組合せ爆発の安全弁）")
    parser.add_argument("--max-paths", type=int, default=1000, dest="max_paths",
                        help="chain 列挙の最大本数（既定 1000）")
    parser.add_argument("--memory-limit", type=int, default=None, dest="memory_limit_mb",
                        help="決定的メモリ近似に基づく degrade トリガ（MB・既定なし）")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--use-ripgrep", dest="use_ripgrep", action="store_const",
                   const=True, default=None,
                   help="ripgrep prefilter を強制 ON（既定は閾値自動判定）")
    g.add_argument("--no-use-ripgrep", dest="use_ripgrep", action="store_const",
                   const=False, help="ripgrep prefilter を強制 OFF")
    parser.add_argument("--ripgrep-threshold-bytes", type=int, default=1 << 30,
                        dest="ripgrep_threshold_bytes",
                        help="自動 ON する総バイト閾値（既定 1GiB）")
    parser.add_argument("--max-passes", type=int, default=8, dest="max_passes",
                        help="（内部）最大パス数")
    parser.add_argument("--progress", default="off", choices=["on", "off"],
                        help="進捗表示 on/off（既定 off）")
    parser.add_argument("--resume", action="store_true",
                        help="完了済みキーワードをスキップ（manifest で完了判定）")
    parser.add_argument("--output-encoding", default="utf-8-sig", dest="output_encoding",
                        help="出力 TSV のエンコーディング（既定 utf-8-sig）")
    parser.add_argument("--encoding-fallback", default="cp932,euc-jp,latin-1",
                        dest="encoding_fallback",
                        help="入力/ソース復号のフォールバック鎖（カンマ区切り・空は既定鎖へ復帰）")
    parser.add_argument("--max-rows-per-part", type=int, default=1_048_575,
                        dest="max_rows_per_part",
                        help="超過時 <kw>.partNN.tsv へ Excel 互換分割（既定 1048575）")
    parser.add_argument("--diagnostics-detail-limit", type=int, default=1000,
                        dest="diagnostics_detail_limit",
                        help="diagnostics 詳細の縮約上限（0 で無制限＝従来同値）")
    parser.add_argument("--decode-cache-dir", default=None, dest="decode_cache_dir",
                        help="復号/言語判定の永続キャッシュ置き場（run跨ぎ再利用可。無指定はrun専用temp）")
    parser.add_argument("--fast-encoding", action="store_true", dest="fast_encoding",
                        help="chardet 前に fallback 鎖で strict 復号を試みる高速路（opt-in・SJIS 多数環境向け）")
    parser.add_argument("--no-perkw-diag", dest="perkw_diag", action="store_false",
                        default=True,
                        help="per-keyword の rg 再走査を省く（高速化。diagnostics の decode_replaced 帰属のみ変化・TSV不変）")
    return parser


def _opts_from(args: argparse.Namespace) -> EngineOptions:
    """parse 済み Namespace から EngineOptions を生成する。"""
    return EngineOptions(
        max_depth=args.max_depth, min_specificity=args.min_specificity,
        stoplist_path=Path(args.stoplist) if args.stoplist else None,
        lang_map=_parse_lang_map(args.lang_map), include=args.include,
        exclude=args.exclude if args.exclude is not None else list(DEFAULT_EXCLUDE),
        jobs=args.jobs, follow_symlinks=args.follow_symlinks,
        max_file_bytes=args.max_file_bytes, max_symbols=args.max_symbols,
        max_paths=args.max_paths,
        memory_limit_mb=args.memory_limit_mb, use_ripgrep=args.use_ripgrep,
        ripgrep_threshold_bytes=args.ripgrep_threshold_bytes,
        max_passes=args.max_passes, progress=args.progress,
        resume=args.resume,
        output_encoding=args.output_encoding,
        encoding_fallback=tuple(
            s for s in args.encoding_fallback.split(",") if s),
        max_rows_per_part=args.max_rows_per_part,
        diagnostics_detail_limit=args.diagnostics_detail_limit,
        decode_cache_dir=Path(args.decode_cache_dir) if args.decode_cache_dir else None,
        fast_encoding=args.fast_encoding,
        perkw_diag=args.perkw_diag,
    )


def _build_opts(argv: list[str] | None = None) -> EngineOptions:
    """argv をパースし EngineOptions を返す（テスト・CLI 補助用）。"""
    args = _make_parser().parse_args(argv)
    return _opts_from(args)


def main(argv: list[str] | None = None) -> int:
    """引数をパースし direct＋不動点パイプラインを実行する。"""
    parser = _make_parser()
    args = parser.parse_args(argv)
    # 出力に影響する入力を早期検証（静黙終了/異常挙動を防ぐ）。
    if not Path(args.input).is_dir():
        parser.error(f"--input directory not found: {args.input}")
    if not Path(args.source_root).is_dir():
        parser.error(f"--source-root directory not found: {args.source_root}")
    if args.jobs < 1:
        parser.error("--jobs must be >= 1")
    if args.max_depth < 0:
        parser.error("--max-depth must be >= 0")
    if args.max_rows_per_part < 1:
        parser.error("--max-rows-per-part must be >= 1")
    # 負値・degenerate な数値は黙って劣化出力を出さず明示エラーにする。
    # memory_limit は 0=最大縮退の意図的指定を許容し、負値のみ拒否
    # （負値だと item 予算が負になり 0 件でも超過扱い＝常時最大縮退）。
    if args.memory_limit_mb is not None and args.memory_limit_mb < 0:
        parser.error("--memory-limit must be >= 0")
    if args.min_specificity < 0:
        parser.error("--min-specificity must be >= 0")
    if args.max_file_bytes < 0:                      # 負値だと全ファイルが large 扱いで空出力になる
        parser.error("--max-file-bytes must be >= 0")
    if args.max_symbols < 1:
        parser.error("--max-symbols must be >= 1")
    if args.max_paths < 1:
        parser.error("--max-paths must be >= 1")
    if args.max_passes < 1:
        parser.error("--max-passes must be >= 1")
    if args.ripgrep_threshold_bytes < 0:
        parser.error("--ripgrep-threshold-bytes must be >= 0")
    # ユーザ提供 stoplist の不在/不可読は load_stoplist の未捕捉例外になる前に弾く。
    if args.stoplist is not None and not Path(args.stoplist).is_file():
        parser.error(f"--stoplist file not found: {args.stoplist}")
    opts = _opts_from(args)
    return run(input_dir=Path(args.input), output_dir=Path(args.output),
               source_root=Path(args.source_root), opts=opts)
