"""任意 ripgrep 一次粗フィルタ。walk の上位集合である（.gitignore/

隠し/バイナリを除外しない＝バイナリ境界は walk の _is_binary に一本化する）。rg
不在/失敗は None＝フィルタ無効（全件走査）となる。出力は不変である（除外 relpath は
部分文字列すら持たず automaton 0 ヒットが確定する）。
"""

import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
from importlib.resources import files as _ir_files
from pathlib import Path

_MACHINE_ALIASES = {
    "aarch64": "aarch64", "arm64": "aarch64",
    "x86_64": "x86_64", "amd64": "x86_64", "AMD64": "x86_64",
}


def _normalize_machine(machine: str) -> str | None:
    """platform.machine() の表記ゆれを同梱ディレクトリ名へ正規化（未知は None）。"""
    return _MACHINE_ALIASES.get(machine)


# オフライン wheelhouse → pip install → 展開済み site-packages のディレクトリインストール
# を前提とする。zip-import のように実体パスを持たない場合は _vendored_rg_path() の
# .is_file() が例外を投げ→捕捉→None へ縮退（PATH フォールバック）するのでクラッシュしない。
# as_file()/ExitStack による実体化は本配備モデルでは不要である。
def _default_vendor_root():
    try:
        return _ir_files("grep_analyzer") / "vendor" / "ripgrep"
    except Exception:
        return None


_VENDOR_ROOT = _default_vendor_root()


def _vendored_rg_path():
    """現 arch の同梱 rg のパスを返す（存在すれば）。未知 arch / 不在は None。

    副作用フリー（存在判定のみ）。実行ビット補完（chmod）は副作用が許される
    `_resolve_rg` が `_ensure_vendored_executable` で行う。これにより
    `available()` から呼ばれても共有/読み取り専用 FS で chmod を起こさない。
    """
    arch = _normalize_machine(platform.machine())
    if arch is None or _VENDOR_ROOT is None:
        return None
    cand = _VENDOR_ROOT / arch / "rg"
    try:
        return cand if cand.is_file() else None
    except Exception:
        return None


def _ensure_vendored_executable(path) -> bool:
    """vendored rg の実行ビットが落ちていれば補う。副作用ありで `_resolve_rg` 専用である。
    付けられなければ False を返す（採用しない）。env/which には使わない。"""
    try:
        if os.access(path, os.X_OK):
            return True
        os.chmod(path, 0o755)
        return True
    except OSError:
        return False


def _verify_sha256(rg_path) -> bool:
    """併置 `<rg>.sha256`（16進1行）と実バイトの sha256 を照合する。sidecar 不在は False。"""
    side = Path(str(rg_path) + ".sha256")
    try:
        want = side.read_text(encoding="ascii").strip().split()[0].lower()
        got = hashlib.sha256(Path(rg_path).read_bytes()).hexdigest()
        return got == want
    except (OSError, IndexError):
        return False


_GREP_ANALYZER_RG_ENV = "GREP_ANALYZER_RG"
_RG_CACHE = None
_RG_RESOLVED = False


def _rg_candidates(env, vendored, which):
    """rg 候補を優先順位（env→同梱→which）で返す（None は除外）。順序の単一情報源である。"""
    return [c for c in (env, vendored, which) if c]


def _resolve_rg_impl(env, vendored, which):
    """採用順（env→同梱→which）で最初の非 None を返す純粋な選択である。"""
    cands = _rg_candidates(env, vendored, which)
    return cands[0] if cands else None


def _smoke_ok(rg_path) -> bool:
    """`rg --version` rc=0 でスモークする（副作用なし＝候補バイナリを変更しない）。"""
    try:
        r = subprocess.run([str(rg_path), "--version"], capture_output=True,
                           check=False, timeout=5)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _resolve_rg(force: bool = False):
    """env→同梱(sha256照合)→which の順で実行可能な rg を解決（run 単位キャッシュ・副作用あり）。"""
    global _RG_CACHE, _RG_RESOLVED
    if _RG_RESOLVED and not force:
        return _RG_CACHE
    env = os.environ.get(_GREP_ANALYZER_RG_ENV) or None
    vendored = _vendored_rg_path()
    if vendored is not None and (
            not _verify_sha256(vendored) or not _ensure_vendored_executable(vendored)):
        vendored = None
    which = shutil.which("rg")
    _RG_CACHE = None
    for c in _rg_candidates(env, str(vendored) if vendored else None, which):
        if _smoke_ok(c):
            _RG_CACHE = c
            break
    _RG_RESOLVED = True
    return _RG_CACHE


def available() -> bool:
    """rg が解決可能か（副作用フリー＝存在判定のみ。chmod/スモークを起こさない）。

    True でも prefilter 経路の _resolve_rg() がスモーク失格で None になり得る
    （available は gate ヒント、prefilter が権威）。
    collect フェーズから安全に呼べる。
    """
    if os.environ.get(_GREP_ANALYZER_RG_ENV):
        return True
    if _vendored_rg_path() is not None:
        return True
    return shutil.which("rg") is not None


# 明示パス渡しの 1 回の rg 呼び出しに載せる引数バイト量の上限で、ARG_MAX に余裕を
# 持たせた値である。Linux の ARG_MAX は概ね 2MiB だが、環境変数・他の固定引数の取り分を
# 引いて保守的に抑えている。
# 超える候補数はチャンク分割し結果を union する（チャンク境界は集合に影響しない）。
_ARG_BYTES_BUDGET = 512 * 1024


def _run_rg_list(rg, pat_path, root, paths):
    """`rg -l -f pat` を paths（None なら全件 `.`）に対し実行し relpath 集合を返す。

    rg 不在/失敗（rc ∉ {0,1}）は None。-a で rg のバイナリ skip を無効化し
    walk の _is_binary を唯一の境界に統一。明示パス渡しでは ignore 規則は
    適用されないが、`.` 走査時との挙動統一のためフラグは据え置く。
    """
    args = [rg, "-l", "-F", "-a", "--no-messages", "--no-ignore", "--hidden",
            "--no-require-git", "-f", pat_path]
    # `--` 区切り必須：corpus 由来の relpath は `-foo.c` のように `-` 始まりがあり得る。
    # 区切りが無いと rg がフラグと誤認し rc=2 で落ち、prefilter が None→全件走査へ
    # フォールバックして per-keyword の encoding_of/decode_replaced 帰属が崩れる（決定性違反）。
    args.append("--")
    args += list(paths) if paths is not None else ["."]
    try:
        # text=False（bytes 出力）: SJIS 等の非 UTF-8 ファイル名を rg が生バイトで出力するため
        # text=True だと UTF-8 デコードで全体が落ちる。bytes で受け、os.fsdecode
        # （FS codec＋surrogateescape）で walk.py の relpath 表現と一致させる。
        proc = subprocess.run(args, cwd=str(root), capture_output=True, check=False)
    except OSError:
        return None
    if proc.returncode not in (0, 1):
        return None
    hit = set()
    for raw in proc.stdout.split(b"\n"):
        if not raw:
            continue
        if raw.startswith(b"./"):
            raw = raw[2:]
        hit.add(os.fsdecode(raw))
    return hit


def _chunk_paths(paths: list[str]):
    """明示パス渡し用に paths を _ARG_BYTES_BUDGET ごとのチャンクへ分割する。

    1 パスが単独で予算超でも必ず 1 つのチャンクに載せる（無限分割を避ける）。
    """
    chunk: list[str] = []
    size = 0
    for p in paths:
        b = len(os.fsencode(p)) + 1          # 区切り分を概算
        if chunk and size + b > _ARG_BYTES_BUDGET:
            yield chunk
            chunk, size = [], 0
        chunk.append(p)
        size += b
    if chunk:
        yield chunk


def prefilter(
    root: Path, rel_to_abs: dict[str, Path], symbols: list[str],
    restrict_to: set[str] | None = None,
) -> set[str] | None:
    """symbols のいずれかの部分文字列を含む relpath 集合（walk 上位集合）を返す。

    rg 不在/失敗は None（呼出側はフィルタ無効＝全 relpath 走査）。symbols 空は空集合。
    -a で rg のバイナリ skip を無効化し walk の _is_binary を唯一の境界に統一。

    `restrict_to` を与えると rg の探索対象を全ツリー `.` ではなくその relpath 集合に
    限定する（明示パス渡し・ARG_MAX 超は分割 union）。lock-step の per-keyword
    prefilter で `restrict_to=union_keep` とすると、keep_k ⊆ union_keep（記号集合の
    部分集合性ゆえ部分文字列マッチも上位集合）により結果は全コーパス走査と同集合だが、
    探索空間が union_keep に縮小される。空候補は rg を起動せず set()。
    """
    rg = _resolve_rg()
    if rg is None:
        return None
    if not symbols:
        return set()
    if restrict_to is not None and not restrict_to:
        return set()                         # 候補なし＝rg 起動不要（keep_k ⊆ ∅）
    # rg は生バイトを -F 検索するが、symbol は復号テキスト由来。非 ASCII の
    # symbol は非 UTF-8 ファイル（cp932/euc-jp 等）でバイト不一致となり、
    # automaton がヒットするファイルを rg が取りこぼす（出力不変違反）。
    # ASCII symbol は cp932/euc-jp/latin-1/utf-8 で同一バイトなので rg は安全な上位集合。
    # よって非 ASCII symbol を含む hop は prefilter を無効化（None＝全件走査）して出力を保証する。
    if not all(s.isascii() for s in symbols):
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".pat", delete=False,
                                     encoding="utf-8") as pf:
        pf.write("\n".join(symbols))
        pat_path = pf.name
    try:
        if restrict_to is None:
            raw_hits = _run_rg_list(rg, pat_path, root, None)
        else:
            # 明示パス渡しを ARG_MAX 余裕でチャンク分割し結果を union（境界は集合に無影響）。
            # sorted で決定的なチャンク列にする（集合結果には不要だが再現性のため）。
            raw_hits = set()
            for chunk in _chunk_paths(sorted(restrict_to)):
                part = _run_rg_list(rg, pat_path, root, chunk)
                if part is None:
                    raw_hits = None
                    break
                raw_hits |= part
    finally:
        Path(pat_path).unlink(missing_ok=True)
    if raw_hits is None:
        return None
    return {r for r in raw_hits if r in rel_to_abs}
