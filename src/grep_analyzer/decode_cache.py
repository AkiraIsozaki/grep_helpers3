"""decode の永続キャッシュ。値は (text, enc, replaced)。

language/dialect は **キャッシュしない**。キーは realpath で正規化されるため
（symlink/綴り違いで同一実体を共有・#2）、relpath 由来の language/dialect を値に含めると
別 relpath（例: `link.sql`→実体 `real.c`）が同一アーティファクトを共有した瞬間に
先勝ちの言語で誤分類され非決定になる（H2）。decode 結果（text/enc/replaced）はバイト
（＋namespace の fast/fallback）にのみ依存するのでキャッシュ安全だが、language/dialect は
relpath 依存なので呼出側（_scan._meta_from_text）が hit ごとに relpath から再導出する。

キーに (realpath, mtime_ns, size, namespace) を含むため hop・worker・run を
またいで安全に共有でき、ソース変更時は自動でミスする。パスは realpath で正規化し、
direct/seed/scan/finalize が綴り違い（source_root/relpath と walk 由来 abspath、
symlink 経由など）でも同一 decode アーティファクトを共有する（#2）。アーティファクトは
disk 上の 1 ファイル（1行 JSON ヘッダ ＋ 改行 ＋ 復号UTF-8本文）として保存する。

耐久性より速度を優先し fsync はしない（本キャッシュは純粋な再計算可能キャッシュで、
クラッシュで失っても次 run が再 decode するだけ）。代わりにヘッダへ本文バイト長
`blen` を持たせ、get で実バイト長と照合して truncated／torn write を miss として
弾く（破損アーティファクトを正本として信用しない・#8）。
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path

_TMP_PREFIX = "ga_dca_"


class DecodeCache:
    def __init__(self, cache_dir: "Path | None", namespace: str = "",
                 max_bytes: "int | None" = None) -> None:
        self._dir = Path(cache_dir) if cache_dir is not None \
            else Path(tempfile.mkdtemp(prefix="ga_decode_"))
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ns = namespace
        self._max_bytes = max_bytes
        self.put_failures = 0           # put が OSError（disk full 等）で no-op になった回数
        # 概算常駐バイト。これが上限を超えたときだけ実走査の退避を起こす（put 毎の全走査＝
        # O(n^2) を回避）。既存ディレクトリ再利用時は初期サイズを実測して種にする。
        self._approx_bytes = self._scan_total() if max_bytes is not None else 0
        self._sweep_stale_temp()

    def _iter_artifacts(self):
        """*.dca の (mtime_ns, size, path) を列挙する（stat 不可の項目は飛ばす）。"""
        for p in self._dir.glob("*.dca"):
            try:
                stt = p.stat()
            except OSError:
                continue
            yield stt.st_mtime_ns, stt.st_size, p

    def _scan_total(self) -> int:
        total = 0
        try:
            for _mt, size, _p in self._iter_artifacts():
                total += size
        except OSError:
            pass
        return total

    def _sweep_stale_temp(self) -> None:
        """クラッシュ/SIGKILL で残った temp（ga_dca_*.tmp）を起動時に掃除する（R-2）。

        既知の軽微な制約（M）: 同一 --decode-cache-dir を 2 run が並走すると、起動時の
        本掃除が他 run の進行中 .tmp を消し得る。その put は os.replace で FileNotFoundError
        → put_failures に落ちるだけで、出力は不変（キャッシュ取りこぼし＝再 decode）。
        共有ディレクトリの並走運用は性能最適化目的のため、この取りこぼしは許容する。
        """
        try:
            for p in self._dir.glob(_TMP_PREFIX + "*.tmp"):
                try:
                    p.unlink()
                except OSError:
                    pass
        except OSError:
            pass

    def _canon(self, abspath: str) -> str:
        """パスを realpath で正規化する（symlink/綴り違いで同一実体を共有する・#2）。"""
        try:
            return os.path.realpath(abspath)
        except OSError:
            return os.fspath(abspath)

    def _file_sig(self, real: str):
        """ファイル署名 (mtime_ns, size) を返す。存在しなければ None を返す。"""
        try:
            st = os.stat(real)
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def _artifact_path(self, real: str, sig) -> Path:
        mtime_ns, size = sig
        key = f"{self._ns}\0{real}\0{mtime_ns}\0{size}"
        h = hashlib.sha1(key.encode("utf-8", "surrogatepass")).hexdigest()
        return self._dir / f"{h}.dca"

    def _discard(self, path: Path) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass

    def _read_header(self, path: Path):
        """アーティファクトを読み (ヘッダ dict, 本文バイト) を返す。

        読込不可は破棄せず None（単なる miss）。改行なし/非 JSON/非 dict の破損は
        path を破棄して None（破損アーティファクトを正本にしない・L-2/H5）。
        """
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            return None
        nl = raw.find(b"\n")
        if nl < 0:
            self._discard(path)
            return None
        try:
            meta = json.loads(raw[:nl].decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._discard(path)
            return None
        if not isinstance(meta, dict):
            # valid JSON だが dict でない破損形（null/数値/配列/文字列）は、後段の
            # meta.get(...) が AttributeError を投げる前に弾く（resume.py:21 と対称）。
            self._discard(path)
            return None
        return meta, raw[nl + 1:]

    def _decode_body(self, path: Path, meta: dict, body_bytes: bytes):
        """本文を UTF-8 復号し (body, enc, replaced) を返す。破損は破棄して None。"""
        try:
            body = body_bytes.decode("utf-8")
        except UnicodeDecodeError:
            self._discard(path)
            return None
        try:
            # 必須メタキー欠落（旧 5-tuple フォーマット差・部分破損）は KeyError で run を
            # 落とさず miss へ降格する（破損アーティファクトを正本にしない・H5/#8）。
            return (body, meta["enc"], meta["replaced"])
        except KeyError:
            self._discard(path)
            return None

    def get(self, abspath: str):
        real = self._canon(abspath)
        sig = self._file_sig(real)
        if sig is None:
            return None
        path = self._artifact_path(real, sig)
        parsed = self._read_header(path)
        if parsed is None:
            return None
        meta, body_bytes = parsed
        if meta.get("mtime_ns") != sig[0] or meta.get("size") != sig[1]:
            return None                      # sha1 衝突保険（キー以外でも再検証）
        if meta.get("blen") != len(body_bytes):
            self._discard(path)              # truncated/torn write を trust しない（#8）
            return None
        return self._decode_body(path, meta, body_bytes)

    def put(self, abspath: str, meta, sig=None) -> None:
        # meta は (text, enc, replaced[, language, dialect])。language/dialect は
        # relpath 依存なのでキャッシュしない（H2）。後方互換のため余分な要素は無視する。
        # sig（呼出側が read した時点の (mtime_ns, size)）を渡すと、独立 re-stat による
        # 「新 sig に旧本文」の stale 化を防ぐ（L1）。未指定時は従来どおり put 時点で stat。
        real = self._canon(abspath)
        if sig is None:
            sig = self._file_sig(real)
        if sig is None:
            return
        text, enc, replaced = meta[0], meta[1], meta[2]
        path = self._artifact_path(real, sig)
        try:
            # encode を try 内に入れ、lone surrogate 等の UnicodeEncodeError でも run を
            # 倒さず caching を諦める（decode 側は errors=replace なので通常 surrogate は
            # path/filename 由来に限られるが、put も decode と同じ「絶対落とさない」契約に
            # 揃える・H5/L-1）。
            body = text.encode("utf-8")
            header = json.dumps({
                "enc": enc, "replaced": replaced,
                "mtime_ns": sig[0], "size": sig[1],
                "blen": len(body),
            }, ensure_ascii=False)
            fd, tmp = tempfile.mkstemp(dir=str(self._dir),
                                       prefix=_TMP_PREFIX, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(header.encode("utf-8") + b"\n")
                    f.write(body)
                os.replace(tmp, path)        # 原子的に可視化（torn write は get の blen で弾く）
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except (OSError, UnicodeError):
            # disk full 等(OSError)／lone surrogate 等(UnicodeError)は静かに caching を諦める（L-1/H5）
            self.put_failures += 1
            return
        if self._max_bytes is not None:
            self._approx_bytes += len(body)
            if self._approx_bytes > self._max_bytes:
                self._enforce_budget()       # 概算が上限超のときだけ実走査（put 毎の全走査を回避）

    def _enforce_budget(self) -> None:
        """max_bytes 超過時に古い（mtime 昇順）アーティファクトから退避する（R-1）。

        opt-in（max_bytes 指定時のみ）。退避はキャッシュミス＝再 decode に降格するだけで
        出力には影響しない。概算バイトが上限を跨いだときだけ呼ばれ、ここで実サイズを
        再走査して退避し、概算を実値へ同期し直す（amortize で put あたりは安価）。
        """
        try:
            arts = sorted(self._iter_artifacts(), key=lambda t: t[0])  # 古い mtime 先頭
            total = sum(size for _mt, size, _p in arts)
            for _mt, size, p in arts:
                if total <= self._max_bytes:
                    break
                try:
                    p.unlink()
                    total -= size
                except OSError:
                    pass
            self._approx_bytes = total       # 概算を実値（退避後）へ同期
        except OSError:
            pass
