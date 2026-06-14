"""静的シンボル採否ポリシー。汎用名の横展開爆発を篩で防ぐ。

静的ソースのみを対象とする。集合サイズ上限の切り捨ては大域・累積のため fixedpoint 側で行う。
"""

from dataclasses import dataclass
from pathlib import Path

from grep_analyzer.model import ChaseSymbols

_JAVA_KW = frozenset(
    "abstract assert boolean break byte case catch char class const continue default do double "
    "else enum extends final finally float for goto if implements import instanceof int interface "
    "long native new package private protected public return short static strictfp super switch "
    "synchronized this throw throws transient try void volatile while true false null var".split())
_C_KW = frozenset(
    "auto break case char const continue default do double else enum extern float for goto if int "
    "long register return short signed sizeof static struct switch typedef union unsigned void "
    "volatile while inline restrict _Bool".split())
_SQL_KW = frozenset(
    "select insert update delete from where and or not null is in like between exists into values "
    "set begin end declare if then else elsif loop for while case when decode dual table view "
    "procedure function trigger as order by group having distinct union all "
    # Oracle データ型（型名 var 抽出のすり抜け対策・二次防御。admit は case-sensitive＝大文字形で登録）
    "NUMBER VARCHAR2 VARCHAR CHAR NCHAR CLOB BLOB DATE TIMESTAMP BOOLEAN PLS_INTEGER "
    "BINARY_INTEGER INTEGER FLOAT DECIMAL LONG RAW ROWID".split())
_SHELL_KW = frozenset(
    "if then else elif fi for while until do done case esac in function select time set setenv "
    "unset export readonly local return break continue switch breaksw end foreach endif endsw "
    "echo test true false".split())
_PERL_KW = frozenset(
    "my our local state sub package use require if unless elsif else while until for foreach do "
    "return last next redo eq ne lt gt le ge cmp and or not xor print printf say warn die "
    "qw q qq tr defined undef ref scalar wantarray bless".split())
_GROOVY_KW = frozenset(
    "def class interface enum trait if else while switch case for return break continue "
    "println print final static import package new this super true false null void in as "
    "instanceof try catch finally throw throws assert abstract extends implements".split())
_PYTHON_KW = frozenset(
    "False None True and as assert async await break class continue def del elif else "
    "except finally for from global if import in is lambda nonlocal not or pass raise "
    "return try while with yield match case self print".split())
_JS_KW = frozenset(
    "break case catch class const continue debugger default delete do else export extends "
    "finally for function if import in instanceof new return super switch this throw try "
    "typeof var void while with yield let static get set of async await null true false "
    "undefined console".split())
_TS_KW = _JS_KW | frozenset(
    "interface type enum namespace declare abstract implements readonly public private "
    "protected as is keyof infer any unknown never number string boolean object".split())
_JSP_KW = _JAVA_KW | frozenset(
    # JSTL 接頭辞・ディレクティブ属性のみ（java 予約語は _JAVA_KW に含む）
    "page include taglib c fn empty".split())
_ANGULAR_KW = _TS_KW | frozenset(
    # _TS_KW に未収録の Angular テンプレ固有語のみ（let/of/async は _JS_KW に既収録）
    "ngIf ngFor ngSwitch ngClass ngStyle ngModel trackBy $event".split())
LANG_KEYWORDS: dict[str, frozenset[str]] = {
    "java": _JAVA_KW, "c": _C_KW, "proc": _C_KW, "sql": _SQL_KW, "shell": _SHELL_KW,
    "perl": _PERL_KW, "groovy": _GROOVY_KW,
    "python": _PYTHON_KW, "javascript": _JS_KW, "typescript": _TS_KW, "tsx": _TS_KW,
    "jsp": _JSP_KW, "html": frozenset(), "angular": _ANGULAR_KW,
    "angular_inline": _ANGULAR_KW}


@dataclass(frozen=True)
class SymbolPolicy:
    """採否の静的パラメータを保持する。大域 cap は fixedpoint 側なので cap は持たない。"""

    min_specificity: int
    user_stoplist: frozenset[str]


@dataclass(frozen=True)
class AdmissionResult:
    """採否の結果を表す。rejected は (シンボル, 理由) の順序保存列である。"""

    accepted: list[str]
    rejected: list[tuple[str, str]]


def load_stoplist(path: Path | None) -> frozenset[str]:
    """ユーザ提供ストップリストを読む。空行と # コメント行を無視（静的）。"""
    if path is None:
        return frozenset()
    out = set()
    for raw in Path(path).read_text("utf-8").splitlines():
        s = raw.strip()
        if s and not s.startswith("#"):
            out.add(s)
    return frozenset(out)


def admit(symbols: list[str], language: str, policy: SymbolPolicy) -> AdmissionResult:
    """シンボル列を静的ポリシーで決定的に採否（cap 非適用）。"""
    kw = LANG_KEYWORDS.get(language, frozenset())
    accepted: list[str] = []
    rejected: list[tuple[str, str]] = []
    for s in symbols:
        if s in kw:
            rejected.append((s, "keyword"))
        elif len(s) < policy.min_specificity:
            rejected.append((s, "too_short"))
        elif s in policy.user_stoplist:
            rejected.append((s, "user_stoplist"))
        else:
            accepted.append(s)
    return AdmissionResult(accepted, rejected)


@dataclass(frozen=True)
class Partition:
    """ChaseSymbols の分割を表す。

    chase=横展開対象（constant/var）、terminal=報告専用（getter/setter）、
    rejected=静的棄却（両方に適用）。大域 cap は fixedpoint 側にある。
    """

    chase: list[str]
    terminal: list[str]
    rejected: list[tuple[str, str]]


def partition(chase_symbols: ChaseSymbols, language: str, policy: SymbolPolicy) -> Partition:
    """ChaseSymbols を chase / terminal / rejected に分割する。

    getter/setter は chase に入れない。keyword/too_short/user_stoplist は両方に適用。
    """
    chase_r = admit(list(chase_symbols.constants) + list(chase_symbols.vars), language, policy)
    term_r = admit(list(chase_symbols.getters) + list(chase_symbols.setters), language, policy)
    return Partition(chase_r.accepted, term_r.accepted, chase_r.rejected + term_r.rejected)
