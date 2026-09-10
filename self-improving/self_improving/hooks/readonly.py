"""Conservative exemption for standalone, inspectable Python read commands.

This is an accidental-write guard, not a sandbox. Unknown syntax stays guarded;
source is parsed only and is never executed here.
"""

import ast
import re
import shlex


_PYTHON = r"(?:/[\w./-]+/)?python(?:\d+(?:\.\d+)*)?"
_FUNCTIONS = {"Path", "print", "enumerate", "str", "len", "range"}
_METHODS = {"read_text", "splitlines", "split", "strip", "get", "items"}
_NODES = (
    ast.Module, ast.Import, ast.ImportFrom, ast.alias, ast.Expr, ast.Assign,
    ast.For, ast.If, ast.Name, ast.Load, ast.Store, ast.Constant, ast.List,
    ast.Tuple, ast.Dict, ast.Call, ast.Attribute, ast.keyword, ast.BinOp,
    ast.Div, ast.Add, ast.JoinedStr, ast.FormattedValue, ast.Subscript,
    ast.Slice, ast.Compare, ast.Eq, ast.NotEq, ast.In, ast.NotIn,
    ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
)


def _source(command: str) -> str | None:
    lines = command.strip().splitlines()
    if not lines:
        return None
    heredoc = re.fullmatch(
        rf"\s*{_PYTHON}\s+-\s*<<\s*(['\"])([A-Za-z_][A-Za-z_0-9]*)\1\s*",
        lines[0],
    )
    if heredoc:
        delimiter = heredoc.group(2)
        if len(lines) < 3 or lines[-1] != delimiter or delimiter in lines[1:-1]:
            return None
        return "\n".join(lines[1:-1])
    # Reject shell expansion even inside quoted -c input. A quoted heredoc
    # above is literal, so Python strings there may safely contain these signs.
    if "$" in command or "`" in command:
        return None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        argv = list(lexer)
    except ValueError:
        return None
    if len(argv) == 3 and re.fullmatch(_PYTHON, argv[0]) and argv[1] == "-c":
        return argv[2]
    return None


def readonly_python(command: str) -> bool:
    if len(command) > 20000:
        return False
    source = _source(command)
    if source is None:
        return False
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return False
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(tree):
        if not isinstance(node, _NODES):
            return False
        if isinstance(node, ast.Import):
            if any(alias.name not in {"pathlib", "json"} or alias.asname for alias in node.names):
                return False
        if isinstance(node, ast.ImportFrom):
            if node.level or node.module != "pathlib" or any(
                alias.name != "Path" or alias.asname for alias in node.names
            ):
                return False
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if node.id in _FUNCTIONS | {"pathlib", "json"}:
                return False
        if isinstance(node, ast.Attribute):
            parent = parents[node]
            if not isinstance(parent, ast.Call) or parent.func is not node:
                return False
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in _FUNCTIONS:
                    return False
                if node.func.id == "print" and any(k.arg not in {"sep", "end"} for k in node.keywords):
                    return False
            elif isinstance(node.func, ast.Attribute):
                func = node.func
                module_call = isinstance(func.value, ast.Name) and (
                    (func.value.id == "json" and func.attr == "loads")
                    or (func.value.id == "pathlib" and func.attr == "Path")
                )
                # JSON decoder hooks can invoke arbitrary callable values even
                # when the AST contains no direct call to those values.
                if module_call and func.attr == "loads" and (len(node.args) != 1 or node.keywords):
                    return False
                if not module_call and func.attr not in _METHODS:
                    return False
            else:
                return False
    return True
