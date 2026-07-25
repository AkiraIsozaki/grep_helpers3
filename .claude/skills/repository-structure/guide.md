# リポジトリ構造定義書作成ガイド

## 基本原則

### 1. 役割の明確化

各ディレクトリ（サブパッケージ）・モジュールは単一の明確な役割を持つべきです。

**悪い例**:
```
src/<package>/
├── stuff/           # 曖昧
├── misc/            # 雑多
└── utils/           # 汎用的すぎる
```

**良い例**:
```
src/<package>/
├── cli.py           # CLIエントリポイント・引数解析
├── service/         # ビジネスロジック
├── repository/      # データ永続化
└── validator.py     # 入力検証
```

### 2. レイヤー分離の徹底

アーキテクチャのレイヤー構造をパッケージ構造に反映させます:

```
src/<package>/
├── cli/             # CLIレイヤー
│   └── commands.py  # サブコマンド定義
├── service/         # サービスレイヤー
│   └── task.py      # タスク管理サービス
└── repository/      # データレイヤー
    └── task.py      # タスクリポジトリ
```

### 3. 技術要素ベースの分割(基本)

関連する技術要素ごとにモジュール・サブパッケージを分割します:

**基本構造**:
```
src/<package>/
├── cli.py           # 引数解析・出力整形
├── service/         # ビジネスロジック
├── repository/      # データ永続化
└── model.py         # ドメインモデル・DTO
```

**レイヤー構造との対応**:
```
CLI/プレゼンテーションレイヤー → cli.py, output_writer.py
サービスレイヤー              → service/
データレイヤー                → repository/, storage/
```

## ディレクトリ構造の設計

### レイヤー構造の表現

```
# 悪い例: 責務の混在した平坦な構造（規模が大きくなった場合）
src/<package>/
├── task_cli.py
├── task_service.py
├── task_repository.py
├── user_cli.py
├── user_service.py
└── user_repository.py

# 良い例: レイヤーを明確に
src/<package>/
├── cli/
│   ├── task.py
│   └── user.py
├── service/
│   ├── task.py
│   └── user.py
└── repository/
    ├── task.py
    └── user.py
```

なお、小規模なうちは `src/<package>/` 直下の平坦なモジュール構成でも問題ありません。モジュール数が増えてきた時点でサブパッケージ化を検討します（後述「スケーリング戦略」）。

### テストディレクトリの配置

**推奨構造**（src レイアウト + トップレベル tests/）:
```
project/
├── src/
│   └── <package>/
│       └── service/
│           └── task.py
└── tests/
    ├── unit/
    ├── integration/
    └── ...
```

**理由**:
- pytest の標準的なプロジェクトレイアウトに準拠
- テストコードが本番コードと分離され、配布物に含まれない
- src レイアウトにより「インストールされたパッケージ」をテストする形になる
- テストタイプごとに整理可能

テスト層の詳細な縄張り（各ディレクトリの役割・やってはいけないこと）は `writing-tests` スキルを使用してください。

## 命名規則のベストプラクティス

### モジュール・パッケージ名の原則

**1. 小文字スネークケースを使う (PEP 8 準拠)**
```
✅ service/
✅ repository/
✅ output_writer.py

❌ Services/
❌ Repository/
❌ OutputWriter.py
```

理由: PEP 8 のモジュール・パッケージ命名規約に準拠（小文字、必要ならアンダースコア）

**2. 単数形を基本とする**
```
✅ service/
✅ classifier/

❌ services/
❌ classifiers_and_helpers/
```

**3. 具体的な名前を使う**
```
✅ validator.py       # 入力検証
✅ formatter.py       # データ整形
✅ parser.py          # データ解析

❌ util.py            # 汎用的すぎる
❌ helper.py          # 曖昧
❌ common.py          # 意味不明
```

### ファイル名・クラス名の原則

**1. モジュールファイル: snake_case**
```python
# サービスモジュール
task_service.py
user_authentication.py

# リポジトリモジュール
task_repository.py
```

**2. クラス名: PascalCase（モジュール内で定義）**
```python
# task_service.py 内
class TaskService: ...

# model.py 内
class Task: ...
class TaskStatus(Enum): ...
```

**3. 抽象インターフェース: Protocol / ABC**
```python
# ports.py などにインターフェースを定義
from typing import Protocol

class TaskStore(Protocol):
    """タスク永続化の抽象インターフェース。"""
    def save(self, task: Task) -> None: ...

# 実装クラス
class FileTaskStore:
    """ファイルベースの TaskStore 実装。"""
```

**4. 定数: モジュールレベルで UPPER_SNAKE_CASE**
```python
# constants.py または各モジュール先頭
DEFAULT_BATCH_SIZE = 1000
ERROR_MESSAGES = {...}
```

## 依存関係の管理

### レイヤー間の依存ルール

```python
# ✅ 良い例: 上位レイヤーから下位レイヤーへの依存
# cli/task.py
from <package>.service.task import TaskService

class TaskCli:
    def __init__(self, task_service: TaskService) -> None:
        self._task_service = task_service

# ❌ 悪い例: 下位レイヤーから上位レイヤーへの依存
# service/task.py
from <package>.cli.task import TaskCli  # 禁止！
```

### 循環importの回避

**問題のあるコード**:
```python
# service/task.py
from <package>.service.user import UserService

class TaskService:
    def __init__(self, user_service: UserService) -> None:
        self._user_service = user_service

# service/user.py
from <package>.service.task import TaskService  # 循環import！

class UserService:
    def __init__(self, task_service: TaskService) -> None:
        self._task_service = task_service
```

**解決策1: 共通のインターフェース(Protocol)を抽出**
```python
# ports.py（依存の向きを断ち切る共通モジュール）
from typing import Protocol

class TaskPort(Protocol):
    """タスク操作の抽象インターフェース。"""
    ...

class UserPort(Protocol):
    """ユーザー操作の抽象インターフェース。"""
    ...

# service/task.py
from <package>.ports import UserPort

class TaskService:
    def __init__(self, user_service: UserPort) -> None:
        self._user_service = user_service

# service/user.py
from <package>.ports import TaskPort

class UserService:
    def __init__(self, task_service: TaskPort) -> None:
        self._task_service = task_service
```

**解決策2: 依存関係を見直す**
```python
# 共通の機能を別サービスに抽出
# service/notification.py
class NotificationService:
    """通知処理を一手に担う。"""

    def notify_task_assignment(self, task_id: str, user_id: str) -> None:
        """タスク割当を通知する。"""

# service/task.py
from <package>.service.notification import NotificationService

class TaskService:
    def __init__(self, notification_service: NotificationService) -> None:
        self._notification_service = notification_service

# service/user.py
from <package>.service.notification import NotificationService

class UserService:
    def __init__(self, notification_service: NotificationService) -> None:
        self._notification_service = notification_service
```

## スケーリング戦略

### 推奨構造

**標準パターン**:
```
src/<package>/
├── __init__.py
├── __main__.py          # python -m <package> のエントリポイント
├── cli.py
├── service/
│   ├── task.py
│   └── user.py
├── repository/
│   ├── task.py
│   └── user.py
├── model.py
└── validator.py
```

**理由**:
- レイヤーごとに責務が明確
- 後からのリファクタリングが不要
- チーム開発で統一しやすい

### モジュール分離のタイミング

**分離を検討する兆候**:
1. サブパッケージ内のモジュール数が10個以上
2. 関連する機能がまとまっている
3. 独立してテスト可能
4. 他の機能への依存が少ない

**分離の手順**:
```
# Before: 全てservice/に配置
service/
├── task.py
├── task_validation.py
├── task_notification.py
├── user.py
└── user_auth.py

# After: 機能ごとにサブパッケージ化
service/
├── task/
│   ├── core.py
│   ├── validation.py
│   └── notification.py
└── user/
    ├── core.py
    └── auth.py
```

## 特殊なケースの対応

### 共有コードの配置

**shared/ サブパッケージ**
```
src/<package>/
├── shared/
│   ├── textutil.py       # 複数レイヤーで使う文字列処理
│   ├── model.py          # 共通モデル
│   └── constants.py      # 共通定数
├── cli.py
├── service/
└── repository/
```

**ルール**:
- 本当に複数のレイヤーで使われるもののみ
- 単一レイヤーでしか使わないものは含めない

### 設定ファイルの管理(該当する場合)

```
project-root/
├── pyproject.toml            # パッケージメタデータ・依存・pytest設定
└── requirements.lock         # 再現可能なインストールのためのロックファイル
```

### スクリプトの管理(該当する場合)

```
scripts/
├── build.sh                  # ビルドスクリプト
└── run.sh                    # 実行スクリプト
```

## ドキュメント配置

### ドキュメントの種類と配置先

**プロジェクトルート**:
- `README.md`: プロジェクト概要
- `CONTRIBUTING.md`: 貢献ガイド
- `LICENSE`: ライセンス

**docs/ ディレクトリ（永続ドキュメント）**:
- `product-requirements.md`: PRD
- `functional-design.md`: 機能設計書
- `architecture.md`: アーキテクチャ設計書
- `repository-structure.md`: 本ドキュメント
- `glossary.md`: 用語集

コーディング規約・テスト方針はドキュメントではなく `coding-conventions` スキル・`writing-tests` スキルとして管理されているため、docs/ に重複して書かないこと。

**ソースコード内**:
- docstring: モジュール・クラス・関数の説明（書き方は `coding-conventions` スキルに従う）

## チェックリスト

- [ ] 各モジュール・サブパッケージの役割が明確に定義されている
- [ ] レイヤー構造がパッケージに反映されている
- [ ] 命名規則が一貫している
- [ ] テストコードの配置方針が決まっている
- [ ] 依存関係のルールが明確である
- [ ] 循環importがない
- [ ] スケーリング戦略が考慮されている
- [ ] 共有コードの配置ルールが定義されている
- [ ] 設定ファイルの管理方法が決まっている
- [ ] ドキュメントの配置場所が明確である
