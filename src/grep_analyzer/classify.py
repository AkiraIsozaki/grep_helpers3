"""言語別行分類の共有実装。pipeline と fixedpoint が共通利用する。"""

from grep_analyzer.classifiers.base import ClassifyResult
from grep_analyzer.classifiers.regex_classifier import (
    classify_groovy,
    classify_perl,
    classify_shell,
    classify_sql,
)
from grep_analyzer.classifiers.ts_classifier import classify_ts
from grep_analyzer.embed_preprocess import effective_language

# 正規表現分類へ渡す content の上限（#L）。sql/perl/shell は従来 uncapped で、
# 1 行が極端に長いと per-hit コストが線形に膨らむ（groovy は既に 200 で自衛）。
# カテゴリは行頭付近のトークンで決まるため、十分大きい上限で実分類は不変。
_CLASSIFY_LINE_CAP = 4000


def classify_hit(
    language: str, dialect: str, file_text: str, lineno: int, content: str,
    cache: dict | None = None,
) -> ClassifyResult:
    """1 ヒットを言語別に分類して (category, confidence) を返す。

    java/c/proc/py/js/ts は tree-sitter(high)、sql/perl/groovy/shell は正規表現(medium)。
    未知言語は bourne shell にフォールバックする。
    `cache` を build_snippet と共有すると、同一ファイルの parse を 1 回に集約できる。
    """
    language = effective_language(language, file_text, lineno, cache=cache)
    if language in ("java", "c", "proc", "python", "javascript", "typescript",
                    "tsx", "jsp", "angular", "angular_inline"):
        return classify_ts(language, file_text, lineno, cache=cache)
    if language == "html":
        return ("その他", "high")
    content = content[:_CLASSIFY_LINE_CAP]      # per-hit コストを有界化（#L）
    if language == "sql":
        return classify_sql(content)
    if language == "perl":
        return classify_perl(content)
    if language == "groovy":
        return classify_groovy(content)
    if language == "shell":
        return classify_shell(content, dialect)
    return classify_shell(content, "bourne")
