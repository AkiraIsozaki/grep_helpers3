# リポジトリ構造定義書 (Repository Structure Document)

## プロジェクト構造

```
project-root/
├── src/
│   └── <package>/             # Pythonパッケージ（例: grep_analyzer）
│       ├── __init__.py
│       ├── __main__.py        # python -m <package> のエントリポイント
│       ├── [module1].py       # [説明]
│       ├── [subpackage1]/     # [説明]
│       └── [subpackage2]/     # [説明]
├── tests/                     # テストコード
│   ├── unit/                  # ユニットテスト
│   ├── integration/           # 統合テスト
│   └── [その他の層]/           # プロジェクトのテスト方針に従う
├── docs/                      # プロジェクトドキュメント
├── pyproject.toml             # パッケージメタデータ・依存・ツール設定
├── scripts/                   # ビルド・補助スクリプト（該当する場合）
└── README.md
```

## ディレクトリ詳細

### src/<package>/ (ソースコードディレクトリ)

#### [モジュール/サブパッケージ1]

**役割**: [説明]

**配置ファイル**:
- [ファイルパターン1]: [説明]
- [ファイルパターン2]: [説明]

**命名規則**:
- [規則1]
- [規則2]

**依存関係**:
- 依存可能: [モジュール/サブパッケージ名]
- 依存禁止: [モジュール/サブパッケージ名]

**例**:
```
[サブパッケージ名]/
├── [example_module1].py
└── [example_module2].py
```

#### [モジュール/サブパッケージ2]

**役割**: [説明]

**配置ファイル**:
- [ファイルパターン1]: [説明]

**命名規則**:
- [規則1]

**依存関係**:
- 依存可能: [モジュール/サブパッケージ名]
- 依存禁止: [モジュール/サブパッケージ名]

### tests/ (テストディレクトリ)

テスト層ごとの役割分担・命名・書き方の方針は `writing-tests` スキルを使用すること。ここにはディレクトリ構造のみを定義する。

#### unit/

**役割**: 個々の関数・クラスの細かい仕様の検証

**構造**:
```
tests/unit/
└── test_[module].py
```

**命名規則**:
- ファイル: `test_[テスト対象モジュール名].py`
- 例: `src/<package>/classify.py` → `tests/unit/test_classify.py`

#### integration/

**役割**: CLI/API の境界契約・オプション相互作用・エラー経路の検証

**構造**:
```
tests/integration/
└── test_[feature].py
```

#### [その他の層]

**役割**: [説明（例: golden = 実サンプル変換の完全一致による回帰検出）]

**構造**:
```
tests/[layer]/
└── test_[scenario].py
```

### docs/ (ドキュメントディレクトリ)

**配置ドキュメント**:
- `product-requirements.md`: プロダクト要求定義書
- `functional-design.md`: 機能設計書
- `architecture.md`: アーキテクチャ設計書
- `repository-structure.md`: リポジトリ構造定義書(本ドキュメント)
- `glossary.md`: 用語集

コーディング規約・テスト方針は `coding-conventions` スキル・`writing-tests` スキルとして管理する。

### pyproject.toml (プロジェクト設定)

**記載内容**:
- パッケージメタデータ（名前・バージョン・Python要求バージョン）
- 依存関係（`[project.dependencies]` / `[project.optional-dependencies]`）
- エントリポイント（`[project.scripts]`）
- ツール設定（`[tool.pytest.ini_options]` 等）

### scripts/ (スクリプトディレクトリ - 該当する場合)

**配置ファイル**:
- ビルドスクリプト
- 開発補助スクリプト

## ファイル配置規則

### ソースファイル

| ファイル種別 | 配置先 | 命名規則 | 例 |
|------------|--------|---------|-----|
| [種別1] | [配置先] | [規則] | [例] |
| [種別2] | [配置先] | [規則] | [例] |

### テストファイル

| テスト種別 | 配置先 | 命名規則 | 例 |
|-----------|--------|---------|-----|
| ユニットテスト | tests/unit/ | test_[対象].py | test_classify.py |
| 統合テスト | tests/integration/ | test_[機能].py | test_cli_options.py |
| [その他の層] | tests/[layer]/ | test_[シナリオ].py | [例] |

### 設定ファイル

| ファイル種別 | 配置先 | 命名規則 |
|------------|--------|---------|
| パッケージ・ビルド設定 | プロジェクトルート | pyproject.toml |
| 依存ロック | プロジェクトルート | requirements.lock |

## 命名規則

### モジュール・パッケージ名

- **レイヤーサブパッケージ**: 単数形、小文字
  - 例: `service/`, `repository/`, `snippet/`
- **モジュール**: snake_case（ハイフン不可）
  - 例: `output_writer.py`, `decode_cache.py`

### クラス・関数名

- **クラス**: PascalCase
  - 例: `TaskService`, `OutputWriter`
- **関数・メソッド・変数**: snake_case
  - 例: `create_task()`, `batch_size`
- **列挙型**: クラス名は PascalCase、メンバーは UPPER_SNAKE_CASE
  - 例: `TaskStatus.IN_PROGRESS`

### テストファイル名

- パターン: `test_[テスト対象モジュール名].py`
- 例: `test_classify.py`, `test_output_writer.py`
- テストメソッド名は日本語（`writing-tests` スキルに従う）

## 依存関係のルール

### レイヤー間の依存

```
CLIレイヤー (cli)
    ↓ (OK)
サービスレイヤー (service)
    ↓ (OK)
データレイヤー (repository)
```

**禁止される依存**:
- データレイヤー → サービスレイヤー
- データレイヤー → CLIレイヤー
- サービスレイヤー → CLIレイヤー

### モジュール間の依存

**循環importの禁止**:
```python
# ❌ 悪い例: 循環import
# module_a.py
from <package>.service.module_b import B

# module_b.py
from <package>.service.module_a import A  # 循環import
```

**解決策**:
```python
# ✅ 良い例: 共通インターフェース(Protocol)の抽出
# ports.py
from typing import Protocol

class SharedType(Protocol): ...

# module_a.py
from <package>.ports import SharedType

# module_b.py
from <package>.ports import SharedType
```

## スケーリング戦略

### 機能の追加

新しい機能を追加する際の配置方針:

1. **小規模機能**: 既存モジュール・サブパッケージに配置
2. **中規模機能**: レイヤー内にサブパッケージを作成
3. **大規模機能**: 独立したサブパッケージとして分離

**例**:
```
src/<package>/
├── service/
│   ├── user.py                      # 既存機能
│   └── task/                        # 中規模機能の分離
│       ├── core.py
│       ├── subtask.py
│       └── category.py
```

### ファイルサイズの管理

**ファイル分割の目安**:
- 1ファイル: 300行以下を推奨
- 300-500行: リファクタリングを検討
- 500行以上: 分割を強く推奨

**分割方法**:
```
# 悪い例: 1ファイルに全機能
# task_service.py (800行)

# 良い例: 責務ごとに分割
# task_service.py (200行) - CRUD操作
# task_validation.py (150行) - バリデーション
# task_notification.py (100行) - 通知処理
```

## 特殊ディレクトリ

### .steering/ (ステアリングファイル)

**役割**: 特定の開発作業における「今回何をするか」を定義（`steering` スキルが管理）

**構造**:
```
.steering/
└── [YYYYMMDD]-[task-name]/
    ├── requirements.md      # 今回の作業の要求内容
    ├── design.md            # 変更内容の設計
    └── tasklist.md          # タスクリスト
```

**命名規則**: `20250115-add-user-profile` 形式

### .claude/ (Claude Code設定)

**役割**: Claude Code設定とカスタマイズ

**構造**:
```
.claude/
├── commands/                # スラッシュコマンド
├── skills/                  # タスクモード別スキル
└── agents/                  # サブエージェント定義
```

## 除外設定

### .gitignore

プロジェクトで除外すべきファイル:
- `__pycache__/`
- `*.pyc`
- `.venv/`
- `dist/`
- `build/`
- `*.egg-info/`
- `.pytest_cache/`
- `.env`
- `.steering/` (タスク管理用の一時ファイル)
- `*.log`
- `.DS_Store`

### テスト・ツールの除外

pytest 等のツールで収集・走査対象から除外すべきディレクトリ:
- `.venv/`
- `build/`, `dist/`
- `.steering/`
- `__pycache__/`
