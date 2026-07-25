# テストのアンチパターン（モック編）

**読むタイミング:** モックを追加するとき、テストを書き換えるとき、プロダクションコードにテスト用の何かを足したくなったとき。

## 概要

テストは**実物の挙動**を検証する。モックは隔離の手段であって、検証対象ではない。

**核心原則:** コードが何をするかをテストする。モックが何をするかではない。

## 3つの鉄則

```
1. モックの挙動をテストしない
2. テスト専用メソッドをプロダクションクラスに足さない
3. 依存を理解せずにモックしない
```

## アンチパターン 1: モックの挙動をテストする

**違反:**

```python
# NG: スタブに仕込んだ値がそのまま返ることを検証している
def test_走査結果を返す(monkeypatch):
    monkeypatch.setattr(scanner, "scan_tree", lambda root: ["a.c", "b.c"])
    result = scanner.scan_tree(Path("/repo"))
    assert result == ["a.c", "b.c"]  # モックが動いた、以上。
```

**なぜ駄目か:** 検証できたのは monkeypatch が機能することだけ。実コードの挙動については何も証明していない。

**修正:** 実物を実データで動かす。grep_analyzer の外部境界はファイルシステムとサブプロセスだけなので、大半は `tmp_path` に実ファイルを作れば実物でテストできる。

```python
# OK: 実物の走査を tmp_path 上の実ファイルで検証
def test_拡張子フィルタはcソースのみ収集する(tmp_path):
    (tmp_path / "a.c").write_text("int x;", encoding="utf-8")
    (tmp_path / "note.txt").write_text("memo", encoding="utf-8")
    result = scan_tree(tmp_path)
    assert [p.name for p in result] == ["a.c"]
```

**ゲート:** モック由来の値にアサートする前に問う —「実物の挙動を検証しているか、モックの存在を検証しているか？」後者ならアサーションを消すか、モックを外す。

## アンチパターン 2: テスト専用メソッドをプロダクションへ

**違反:**

```python
# NG: reset_cache() はテストからしか呼ばれない
class EncodingDetector:
    def reset_cache(self):  # プロダクション API に見えてしまう
        self._cache.clear()
```

**なぜ駄目か:** プロダクションクラスがテスト都合で汚染される。本番で誤って呼ばれれば危険。YAGNI と関心の分離に反する。

**修正:** 後始末はテストユーティリティ（conftest.py のフィクスチャ等）が担う。

```python
# OK: conftest.py 側で新インスタンスを都度生成
@pytest.fixture
def detector():
    return EncodingDetector()  # テスト毎に新品。reset は不要
```

**ゲート:** プロダクションクラスにメソッドを足す前に問う —「これはテストからしか使われないか？」Yes なら足さない。テストユーティリティへ。

## アンチパターン 3: 依存を理解せずにモックする

**違反:**

```python
# NG: モックした書き込みに、後続の検証が依存していた
def test_重複出力パスは拒否する(tmp_path, monkeypatch):
    # 「遅そうだから」と出力書き込みを丸ごと潰す
    monkeypatch.setattr(writer, "write_tsv", lambda *a: None)
    run_analysis(tmp_path, out=tmp_path / "r.tsv")
    with pytest.raises(DuplicateOutputError):
        run_analysis(tmp_path, out=tmp_path / "r.tsv")  # ファイルが無いので発生しない！
```

**なぜ駄目か:** モックしたメソッドの副作用（ファイル生成）にテスト自身が依存していた。「安全のため」の過剰モックが実挙動を壊し、テストは謎の失敗か、誤った理由での成功に至る。

**修正:** 実装で一度動かして必要な副作用を観察してから、本当に遅い・外部な最下層だけを最小限にモックする。

```python
# OK: 遅い部分（ripgrep 起動）だけ差し替え、ファイル書き込みは実物のまま
def test_重複出力パスは拒否する(tmp_path, fake_ripgrep):
    run_analysis(tmp_path, out=tmp_path / "r.tsv")   # TSV は実際に書かれる
    with pytest.raises(DuplicateOutputError):
        run_analysis(tmp_path, out=tmp_path / "r.tsv")
```

**ゲート:** モックする前に必ず問う —
1. 実物のメソッドはどんな副作用を持つか？
2. このテストはその副作用のどれかに依存していないか？
3. 不明なら**まず実装のまま実行**し、必要なものを観察してから最小限をモックする。

## モックが複雑になりすぎたら

兆候: モックの準備がテスト本体より長い / 全部モックしないと通らない / モックを外すとテストが壊れる理由を説明できない。

**問い直す:**「そもそもここにモックは要るのか？」 grep_analyzer では実ファイル＋実オブジェクトの古典学派スタイル（`writing-tests` 参照）のほうが、複雑なモックより単純で堅牢なことが多い。

## クイックリファレンス

| アンチパターン | 修正 |
|----------------|------|
| モック値へのアサート | 実物をテストするかモックを外す |
| テスト専用メソッドの混入 | conftest / テストユーティリティへ移す |
| 理解なきモック | 依存を先に理解し、最下層を最小限モック |
| モック準備がテストの過半 | 統合テスト（実物）を検討 |

**結論: モックは隔離の道具であり、テスト対象ではない。** TDD を正しく回していれば（実物相手に赤を見ていれば）これらには陥らない。
