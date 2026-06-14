"""A12: tree-sitter wheel 欠落でも regex トラックは起動可能（遅延 import）。"""
import builtins
import importlib
import sys


def test_tree_sitterパッケージ未importでもclassifyがimportできる(monkeypatch):
    # ts_classifier と classify をキャッシュから外し、tree_sitter_* の import を失敗させる。
    # テスト分離: sys.modules を操作するため、影響キーのスナップショットを取り finally で
    # 完全復元する（さもないと ts_classifier が二重化し、後続テストの monkeypatch が
    # chase.parse_tree の実体に効かなくなる＝テスト汚染）。
    prefixes = ("grep_analyzer.classif", "tree_sitter")
    saved = {k: v for k, v in sys.modules.items() if k.startswith(prefixes)}
    try:
        for name in list(sys.modules):
            if name.startswith(prefixes):
                sys.modules.pop(name, None)
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name.startswith("tree_sitter"):
                raise ModuleNotFoundError(f"No module named {name!r}")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        mod = importlib.import_module("grep_analyzer.classify")
        # regex トラックの分類はモジュール import 時点で tree-sitter を要求しない
        assert mod.classify_hit("shell", "bourne", 'X=1\n', 1, "X=1")[0] != ""
    finally:
        # 本テストで作られた新モジュールを除去し、元のモジュールオブジェクトを復元する。
        for name in list(sys.modules):
            if name.startswith(prefixes):
                sys.modules.pop(name, None)
        sys.modules.update(saved)
