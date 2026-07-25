# アーキテクチャ設計ガイド

## 基本原則

### 1. 技術選定には理由を明記

**悪い例**:
```
- Python
- argparse
```

**良い例**:
```
- Python 3.12
  - 最新の型ヒント構文と性能改善により、保守性と実行効率を両立できる
  - 標準ライブラリが充実しており、CLIツールを最小限の外部依存で構築可能
  - クロスプラットフォームで動作し、配布が容易

- argparse (標準ライブラリ)
  - 追加依存なしでサブコマンド・オプション解析を実現できる
  - ヘルプ表示・型変換・バリデーションを標準でサポート

- pyproject.toml (PEP 621)
  - パッケージメタデータ・依存関係・エントリポイントを1ファイルで宣言的に管理
  - pip / build 等の標準ツールチェーンと直接統合できる
```

### 2. レイヤー分離の原則

各レイヤーの責務を明確にし、依存関係を一方向に保ちます:

```
CLI → Service → Data (OK)
CLI ← Service (NG)
CLI → Data (NG)
```

### 3. 測定可能な要件

すべてのパフォーマンス要件は測定可能な形で記述します。

## レイヤードアーキテクチャの設計

### 各レイヤーの責務

**CLIレイヤー**:
```python
class MatrixCli:
    """責務: ユーザー入力の受付とバリデーション。"""

    def __init__(self, matrix_service: MatrixService) -> None:
        self._matrix_service = matrix_service

    # OK: サービスレイヤーを呼び出す
    def on_calculate(self) -> None:
        result = self._matrix_service.multiply(self._matrix_a, self._matrix_b)
        self._result_view.display(result)

    # NG: データレイヤーを直接呼び出す
    def on_calculate_bad(self) -> None:
        result = self._repository.load(self._matrix_id)  # NG
```

**サービスレイヤー**:
```python
class MatrixService:
    """責務: ビジネスロジックの実装。"""

    def __init__(self, repository: MatrixRepository) -> None:
        self._repository = repository

    def multiply(self, a: Matrix, b: Matrix) -> Matrix:
        """行列演算と結果の保存を行う。"""
        if a.columns != b.rows:
            raise ValueError("行列のサイズが一致しません")
        result = a.multiply(b)
        self._repository.save(result)
        return result
```

**データレイヤー**:
```python
class MatrixRepository:
    """責務: データの永続化。"""

    def save(self, matrix: Matrix) -> None:
        """行列データをストレージへ書き込む。"""
        self._storage.write(matrix)
```

## パフォーマンス要件の設定

### 具体的な数値目標

```
コマンド応答時間: 100ms以内(平均的なPC環境で)
└─ 測定方法: time.perf_counter() でコマンド起動から結果表示まで計測
└─ 測定環境: CPU Core i5相当、メモリ8GB、SSD

行列演算表示: 100x100行列まで1秒以内
└─ 測定方法: ダミーデータで計測
└─ 許容範囲: 10x10で10ms、100x100で1秒、1000x1000で10秒
```

## セキュリティ設計

### データ保護の3原則

1. **最小権限の原則**
```python
import os

# ファイルパーミッション: 所有者のみ読み書き
os.chmod(data_path, 0o600)
```

2. **入力検証**
```python
def validate_dimension(rows: int, cols: int) -> None:
    """行列サイズの妥当性を検証する。"""
    if rows <= 0 or cols <= 0:
        raise ValidationError("行列のサイズは正の整数である必要があります")
    if rows > 10000 or cols > 10000:
        raise ValidationError("行列のサイズは10000以内です")
```

3. **機密情報の管理**
```bash
# 環境変数で管理
export MYTOOL_API_KEY="xxxxx"  # コード内にハードコードしない
```

```python
import os

# Pythonコード内での取得
api_key = os.environ.get("MYTOOL_API_KEY")
if api_key is None:
    raise RuntimeError("環境変数 MYTOOL_API_KEY が設定されていません")
```

## スケーラビリティ設計

### データ増加への対応

**想定データ量**: [例: 10,000件の行列データ]

**対策**:
- データのページネーション
- 古いデータのアーカイブ
- インデックスの最適化

```python
class ArchiveService:
    """アーカイブ機能の例: 古いデータを別ファイルに移動する。"""

    def __init__(self, repository: MatrixRepository, archive_storage: ArchiveStorage) -> None:
        self._repository = repository
        self._archive_storage = archive_storage

    def archive_old_data(self, older_than: datetime) -> None:
        """指定日時より古いデータをアーカイブへ退避する。"""
        old_data = self._repository.find_older_than(older_than)
        self._archive_storage.save(old_data)
        self._repository.delete_all([m.id for m in old_data])
```

## 依存関係管理

### バージョン管理方針

```toml
# pyproject.toml
[project]
dependencies = [
    # 文字コード判定 - 安定版は固定
    "chardet==5.2.0",
    # 高速検索 - マイナーバージョンアップは許可
    "pyahocorasick>=2.1,<3",
]

[project.optional-dependencies]
test = [
    # テスト依存 - メジャーバージョン内で自動更新
    "pytest>=8,<9",
]
```

**方針**:
- 安定版は固定バージョン(`==`)で管理
- 信頼性の高いライブラリはマイナーバージョンまで許可(`>=X.Y,<X+1`)
- テスト依存はメジャーバージョン内のみ自動更新
- ロックファイル(`requirements.lock` 等)で再現可能なインストールを保証
- `pip list` / `pip check` で依存の整合性を定期的に確認

## チェックリスト

- [ ] すべての技術選定に理由が記載されている
- [ ] レイヤードアーキテクチャが明確に定義されている
- [ ] パフォーマンス要件が測定可能である
- [ ] セキュリティ考慮事項が記載されている
- [ ] スケーラビリティが考慮されている
- [ ] バックアップ戦略が定義されている
- [ ] 依存関係管理のポリシーが明確である
- [ ] テスト戦略が定義されている
