
"""OI-084 static guard: production code may not log or store exception text.

For every ``except ... as name`` handler in production code:
  * ``name`` may not appear in a logging call, an f-string, ``str()``/``repr()``/``format()``
    or ``%`` formatting, except inside ``describe_exception(...)``, ``reason_for(...)``,
    ``type(...)`` or as ``exc=`` of ``log_exception``; it may be re-raised or chained.
  * ``logging``'s ``.exception(...)``, ``exc_info=`` and ``stack_info=`` are forbidden
    everywhere in production code (they emit the message and a formatted traceback).

Allow-listed files are listed with a reason; adding to the list is a reviewable decision.
This guard checks exception variables, not every possible log argument (see audit/safe_exc.py).
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {"tests", "adversarial", ".git", "__pycache__", "venv", ".venv", "node_modules", "docs"}
ALLOW = {
    # Governance CLI over repo files; prints validation problems to the operator's terminal.
    "policy/governance/change_log.py": "operator CLI over committed governance files, no request content",
    # The helper itself reads exceptions in order to NOT print them.
    "audit/safe_exc.py": "implements the safe description",
}
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log", "fatal"}
# isinstance() yields a bool, so it cannot carry exception text (used to classify a wrapped timeout).
# Project-defined exceptions whose message is static BY CONSTRUCTION (LLMGatewayError asserts its message is
# one of a fixed set of codes; GatewayConfigError is only raised with literal text naming a variable). A
# handler that catches ONLY these may read the exception. test_static_message_exceptions_are_only_raised_
# with_static_text pins the claim, so this is not an open door.
STATIC_MESSAGE_EXCEPTIONS = {"LLMGatewayError", "GatewayConfigError"}
SAFE_WRAPPERS = {"describe_exception", "reason_for", "type", "isinstance"}


def _production_files():
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT)
        if SKIP_DIRS & set(rel.parts):
            continue
        if rel.as_posix() in ALLOW:
            continue
        yield rel.as_posix(), ast.parse(p.read_text(encoding="utf-8"))


def _catches_only_static_exceptions(h: ast.ExceptHandler) -> bool:
    t = h.type
    names = [e for e in (t.elts if isinstance(t, ast.Tuple) else [t])] if t is not None else []
    return bool(names) and all(
        (isinstance(n, ast.Name) and n.id in STATIC_MESSAGE_EXCEPTIONS)
        or (isinstance(n, ast.Attribute) and n.attr in STATIC_MESSAGE_EXCEPTIONS) for n in names)


def _unsafe_uses(node: ast.AST, name: str):
    """Names bound to the exception that are used outside a safe wrapper."""
    out = []

    def visit(n, safe):
        if isinstance(n, ast.Call):
            fn = n.func
            fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            is_safe = fname in SAFE_WRAPPERS
            for a in n.args:
                visit(a, safe or is_safe)
            for k in n.keywords:
                visit(k.value, safe or is_safe or (fname == "log_exception" and k.arg == "exc"))
            visit(fn, safe)
            return
        if isinstance(n, ast.Name) and n.id == name and not safe:
            out.append(n.lineno)
        for c in ast.iter_child_nodes(n):
            visit(c, safe)

    visit(node, False)
    return out


def test_no_logging_exception_or_exc_info_in_production_code():
    bad = []
    for rel, tree in _production_files():
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            if isinstance(n.func, ast.Attribute) and n.func.attr == "exception" \
                    and isinstance(n.func.value, ast.Name) and n.func.value.id in {"log", "logger", "logging", "_log", "_logger"}:
                bad.append(f"{rel}:{n.lineno} .exception()")
            for k in n.keywords:
                if k.arg in {"exc_info", "stack_info"}:
                    bad.append(f"{rel}:{n.lineno} {k.arg}=")
    assert not bad, "use audit.safe_exc.log_exception instead:\n" + "\n".join(bad)


def test_exception_variables_are_not_logged_or_stored_in_production_code():
    bad = []
    for rel, tree in _production_files():
        for h in ast.walk(tree):
            if not isinstance(h, ast.ExceptHandler) or not h.name:
                continue
            if _catches_only_static_exceptions(h):
                continue
            for stmt in h.body:
                if isinstance(stmt, ast.Raise):
                    continue                     # re-raise / chaining keeps the exception object
                for line in _unsafe_uses(stmt, h.name):
                    bad.append(f"{rel}:{line} uses '{h.name}' outside describe_exception/reason_for")
    assert not bad, "\n".join(bad)


def test_the_guard_catches_a_violation():
    tree = ast.parse("try:\n    pass\nexcept Exception as e:\n    logger.warning('x %s', e)\n")
    h = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    assert _unsafe_uses(h.body[0], "e")
    ok = ast.parse("try:\n    pass\nexcept Exception as e:\n    logger.warning('x %s', describe_exception(e))\n")
    h2 = next(n for n in ast.walk(ok) if isinstance(n, ast.ExceptHandler))
    assert not _unsafe_uses(h2.body[0], "e")


def test_isinstance_is_safe_but_formatting_the_same_attribute_is_not():
    safe = ast.parse("try:\n    pass\nexcept OSError as e:\n    if isinstance(e.reason, TimeoutError):\n        raise TimeoutError\n")
    h = next(n for n in ast.walk(safe) if isinstance(n, ast.ExceptHandler))
    assert not _unsafe_uses(h.body[0], "e")
    for leak in ("logger.warning('x %s', e.reason)", "msg = f'{e.reason}'", "x = str(e.reason)"):
        bad = ast.parse(f"try:\n    pass\nexcept OSError as e:\n    {leak}\n")
        hb = next(n for n in ast.walk(bad) if isinstance(n, ast.ExceptHandler))
        assert _unsafe_uses(hb.body[0], "e"), leak


def test_static_message_exceptions_are_only_raised_with_static_text():
    """Every construction of an exempt exception uses a string literal, or an f-string whose only
    interpolations are the loop-free constants/names listed here (never request-derived values)."""
    allowed_names = {"name", "BACKENDS", "code"}        # env-var names, the backend tuple, a CODES member
    bad = []
    for rel, tree in _production_files():
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in STATIC_MESSAGE_EXCEPTIONS):
                continue
            arg = n.args[0] if n.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                continue
            if isinstance(arg, ast.JoinedStr) and all(
                    isinstance(v, ast.Constant) or (isinstance(v, ast.FormattedValue)
                                                    and isinstance(v.value, ast.Name) and v.value.id in allowed_names)
                    for v in arg.values):
                continue
            if rel == "llm/gateway.py" and isinstance(arg, ast.Name) and arg.id == "code":
                continue                                   # LLMGatewayError(code): asserted against CODES at runtime
            bad.append(f"{rel}:{n.lineno}")
    assert not bad, "exempt exceptions must carry static text only:\n" + "\n".join(bad)


def test_exempt_handlers_are_recognised_only_for_exactly_those_classes():
    ok = ast.parse("try:\n    pass\nexcept LLMGatewayError as e:\n    print(e.code)\n")
    assert _catches_only_static_exceptions(next(n for n in ast.walk(ok) if isinstance(n, ast.ExceptHandler)))
    for src in ("except Exception as e:", "except (LLMGatewayError, OSError) as e:", "except RuntimeError as e:"):
        t = ast.parse(f"try:\n    pass\n{src}\n    pass\n")
        assert not _catches_only_static_exceptions(next(n for n in ast.walk(t) if isinstance(n, ast.ExceptHandler)))
