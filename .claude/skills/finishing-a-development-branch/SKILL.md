---
name: finishing-a-development-branch
description: 実装が完了し全テストが通り、作業の統合方法（マージ・PR・保持・破棄）を決めるときに使用
---

# 開発ブランチの完了

## 概要

明確な選択肢を提示し、選ばれたワークフローを実行して開発作業を完了させる。

**基本原則:** テスト検証 → 環境検出 → ベースブランチ特定 → 選択肢提示 → 実行 → 掃除。

**開始時に宣言:** 「finishing-a-development-branch スキルでこの作業を完了させる。」

## 手順

### Step 1: テスト検証

選択肢を提示する**前に**テストが通ることを確認する:

```bash
python -m pytest tests/ -q --tb=line
```

**失敗した場合:** 失敗内容を提示し、「テスト失敗 (<N>件)。完了前に修正が必須。テストが通るまでマージ/PR には進めない」と述べて**停止**。選択肢は提示しない。

**成功した場合:** Step 2 へ。

### Step 2: 環境検出

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
```

| 状態 | メニュー | 掃除 |
|------|---------|------|
| `GIT_DIR == GIT_COMMON`（通常リポジトリ） | 標準4択 | worktree なし |
| `GIT_DIR != GIT_COMMON`・名前付きブランチ | 標準4択 | 出自ベース（Step 6） |
| `GIT_DIR != GIT_COMMON`・detached HEAD | 3択（マージなし） | 掃除しない（外部管理） |

### Step 3: ベースブランチ特定

```bash
git merge-base HEAD main 2>/dev/null   # 本プロジェクトの既定ブランチは main
```

不確かなら質問する: 「このブランチは main から分岐した、で正しいか?」

### Step 4: 選択肢提示（正確にこの選択肢のみ・説明を足さない）

**通常リポジトリ / 名前付きブランチ worktree — 正確に4択:**

```
実装完了。どうするか?
1. <base-branch> へローカルでマージ
2. push して Pull Request を作成
3. ブランチをこのまま維持（後で自分で処理する）
4. この作業を破棄
```

**detached HEAD — 正確に3択:**

```
実装完了。detached HEAD 上（外部管理ワークスペース）。
1. 新ブランチとして push し Pull Request を作成
2. このまま維持（後で自分で処理する）
3. この作業を破棄
```

### Step 5: 選択の実行

**選択肢1: ローカルマージ**
```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"
git checkout main && git pull
git merge <feature-branch>
python -m pytest tests/ -q --tb=line   # マージ結果でのテスト確認は削除より先
```
テスト成功後: worktree 掃除（Step 6）→ `git branch -d <feature-branch>`。

**選択肢2: push + PR**
```bash
git push -u origin <feature-branch>
```
worktree は**掃除しない** — PR フィードバックの反復に必要。

**選択肢3: そのまま維持** — 「ブランチ <name> を維持。worktree は <path> に保持」と報告。掃除しない。

**選択肢4: 破棄** — まず確認:
```
以下を完全に削除する:
- ブランチ <name> / 全コミット: <commit-list> / worktree <path>
確認のため 'discard' と入力せよ。
```
ユーザーが正確に `discard` と入力した場合**のみ**実行。MAIN_ROOT へ cd → worktree 掃除（Step 6）→ `git branch -D <feature-branch>`。

### Step 6: ワークスペースの掃除

**選択肢1と4のみ実行。** 2と3は常に worktree を保持する。

- `GIT_DIR == GIT_COMMON`: 通常リポジトリ。掃除対象なし。
- worktree パスが `.worktrees/`・`worktrees/` 配下: 自分たちが作成した worktree — 掃除する。
  ```bash
  MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
  cd "$MAIN_ROOT"                    # 必ず main リポジトリルートから実行
  git worktree remove "$WORKTREE_PATH"
  git worktree prune                 # 古い登録の自己修復
  ```
- それ以外: ハーネス所有のワークスペース。**削除しない**。終了ツール（ExitWorktree 等）があればそれを使う。

順序は必ず: **worktree 削除 → `git branch -d` → `git worktree prune`**（ブランチ削除が先だと worktree が参照していて失敗する）。

## Red Flags

**決してしないこと:**
- テスト失敗のまま先へ進む / マージ結果のテスト確認なしで削除に進む
- 確認なしの作業破棄 / 明示要求なしの force-push
- マージ成功の確認前に worktree を削除する
- 自分が作っていない worktree の掃除（出自確認）
- worktree の**内側から** `git worktree remove` を実行する
- 「次はどうする?」のような曖昧な質問（構造化された4択/3択のみ）

**必ずすること:** 選択肢提示前のテスト検証 / メニュー提示前の環境検出 / 正確に4択（detached HEAD は3択）/ 選択肢4は `discard` のタイプ確認 / 掃除は選択肢1・4のみ / worktree 削除は main リポジトリルートから / 削除後の `git worktree prune`。
