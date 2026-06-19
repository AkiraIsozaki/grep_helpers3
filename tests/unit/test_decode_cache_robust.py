"""decode_cache の get/put が破損入力でクラッシュせず安全に降格することを検証する（H5）。

- get(): ヘッダが valid JSON だが必須キー欠落なら KeyError で落ちず miss(None)へ降格。
- put(): lone surrogate を含むテキストは UnicodeEncodeError で run を倒さず put_failures。
共有キャッシュ破損や FS 走査由来 surrogate が run 全体を落とさないことを保証する。
"""

import json
from pathlib import Path

from grep_analyzer.decode_cache import DecodeCache


def _src(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_必須キー欠落ヘッダのgetはKeyErrorで落ちずmiss降格する(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "a.c", b"int main(){}\n")
    cache.put(str(src), ("int main(){}\n", "utf-8", False, "c", "bourne"))
    # 既存アーティファクトのヘッダから "enc" キーを抜く（blen/mtime/size は維持）。
    dca = next((tmp_path / "cache").glob("*.dca"))
    raw = dca.read_bytes()
    nl = raw.find(b"\n")
    meta = json.loads(raw[:nl].decode("utf-8"))
    del meta["enc"]
    dca.write_bytes(json.dumps(meta, ensure_ascii=False).encode("utf-8")
                    + b"\n" + raw[nl + 1:])
    assert cache.get(str(src)) is None       # KeyError で落ちない


def test_lone_surrogateを含むテキストのputは例外を出さずput_failures(tmp_path):
    cache = DecodeCache(tmp_path / "cache")
    src = _src(tmp_path, "b.txt", b"x")
    bad_text = "ok\udc95tail"               # utf-8 strict で encode 不能
    cache.put(str(src), (bad_text, "utf-8", False, "text", "bourne"))
    assert cache.put_failures == 1
    assert cache.get(str(src)) is None       # put されていない＝miss
