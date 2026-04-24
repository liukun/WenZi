"""Script registry for snippet placeholder expansion.

Snippets use ``{name}`` and ``{name|other}`` syntax to invoke registered
scripts.  Each script is a sync callable that returns ``str``.  Chain
dispatch (``{a|b|c}``) passes each script's result as the first positional
argument to the next script in the chain; the head of the chain receives
no piped input.

Built-ins (``clipboard``, ``date``, ``unwrap``, ...) are registered at
import time using short names.  Plugins register scripts via
``wz.script(name, fn)``; the engine auto-prefixes plugin-registered names
with the plugin id (``<plugin>.<name>``) so plugins cannot collide with
built-ins or each other.

Async script functions are explicitly rejected at registration time —
the snippet expander runs in sync contexts (CGEventTap callback, chooser
source list-builder) and bridging would require a wider asyncio
migration.  See ``dev/asyncio-migration-plan.md``.
"""

from __future__ import annotations

import ast
import inspect
import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

ScriptFn = Callable[..., Any]

_REGISTRY: dict[str, ScriptFn] = {}

# Plugin-registered names must look like "<plugin>.<name>"; built-ins use
# short identifiers.  Hyphens allowed in plugin id segment.
_NAME_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.\-]*)(?:\((.*)\))?$", re.DOTALL)


def register(name: str, fn: ScriptFn) -> None:
    """Register *fn* under *name*.

    Raises ``ValueError`` if *name* is empty or already registered.
    Raises ``TypeError`` if *fn* is an async coroutine function.
    """
    if not name:
        raise ValueError("script name must be non-empty")
    if inspect.iscoroutinefunction(fn):
        raise TypeError(
            f"script {name!r} is async; the snippet expander is sync-only "
            "for now (see dev/asyncio-migration-plan.md)"
        )
    if name in _REGISTRY:
        raise ValueError(f"script {name!r} already registered")
    _REGISTRY[name] = fn


def _register_builtin(name: str, fn: ScriptFn) -> None:
    """Idempotent registration for built-ins (survives module reloads)."""
    if inspect.iscoroutinefunction(fn):
        raise TypeError(f"built-in {name!r} must be sync")
    _REGISTRY[name] = fn


def unregister(name: str) -> None:
    _REGISTRY.pop(name, None)


def lookup(name: str) -> ScriptFn | None:
    return _REGISTRY.get(name)


def _snapshot() -> dict[str, ScriptFn]:
    return dict(_REGISTRY)


def _restore(snapshot: dict[str, ScriptFn]) -> None:
    _REGISTRY.clear()
    _REGISTRY.update(snapshot)


def _split_chain(s: str) -> list[str]:
    """Split *s* on top-level ``|`` (outside string literals and parens)."""
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(s)
    paren_depth = 0
    while i < n:
        ch = s[i]
        if ch in ("'", '"'):
            quote = ch
            triple = s[i : i + 3] == quote * 3
            if triple:
                end = s.find(quote * 3, i + 3)
                if end == -1:
                    raise ValueError(f"unterminated string in {s!r}")
                buf.append(s[i : end + 3])
                i = end + 3
            else:
                j = i + 1
                while j < n:
                    if s[j] == "\\" and j + 1 < n:
                        j += 2
                        continue
                    if s[j] == quote:
                        break
                    j += 1
                if j >= n or s[j] != quote:
                    raise ValueError(f"unterminated string in {s!r}")
                buf.append(s[i : j + 1])
                i = j + 1
        elif ch in "([{":
            paren_depth += 1
            buf.append(ch)
            i += 1
        elif ch in ")]}":
            paren_depth -= 1
            buf.append(ch)
            i += 1
        elif ch == "|" and paren_depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            i += 1
        else:
            buf.append(ch)
            i += 1
    parts.append("".join(buf).strip())
    return parts


def _parse_call(seg: str) -> tuple[str, list[Any], dict[str, Any]]:
    """Parse a chain segment into ``(name, args, kwargs)``.

    The segment is either a bare name (``foo``, ``my-plugin.bar``) or a
    Python-style call (``foo(1, "x", key=2)``).  Arguments must be Python
    literals — identifiers, attribute access, or operators are rejected.
    """
    seg = seg.strip()
    if not seg:
        raise ValueError("empty script segment")
    m = _NAME_RE.match(seg)
    if not m:
        raise ValueError(f"invalid script call: {seg!r}")
    name = m.group(1)
    args_str = m.group(2)
    if args_str is None or not args_str.strip():
        return name, [], {}
    # Wrap as a synthetic call so we can let ast extract args/kwargs.
    try:
        tree = ast.parse(f"_({args_str})", mode="eval")
    except SyntaxError as e:
        raise ValueError(f"syntax error in args of {seg!r}: {e}") from e
    call = tree.body
    if not isinstance(call, ast.Call):
        raise ValueError(f"invalid args in {seg!r}")
    args: list[Any] = []
    for a in call.args:
        try:
            args.append(ast.literal_eval(a))
        except (ValueError, SyntaxError) as e:
            raise ValueError(
                f"non-literal positional argument in {seg!r}: {e}"
            ) from e
    kwargs: dict[str, Any] = {}
    for kw in call.keywords:
        if kw.arg is None:
            raise ValueError(f"**kwargs not allowed in {seg!r}")
        try:
            kwargs[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError) as e:
            raise ValueError(
                f"non-literal keyword argument {kw.arg}= in {seg!r}: {e}"
            ) from e
    return name, args, kwargs


def dispatch(expr: str) -> str:
    """Evaluate a chain expression like ``a|b("x")|c`` and return a string.

    Raises ``KeyError`` if any name is not registered, ``ValueError`` for
    parse/syntax errors, and propagates exceptions from script callables.
    """
    segments = _split_chain(expr)
    if not segments or segments == [""]:
        raise ValueError("empty script expression")
    pipe_value: Any = None
    for i, seg in enumerate(segments):
        name, args, kwargs = _parse_call(seg)
        fn = lookup(name)
        if fn is None:
            raise KeyError(name)
        if i == 0:
            result = fn(*args, **kwargs)
        else:
            result = fn(pipe_value, *args, **kwargs)
        pipe_value = result
    return "" if pipe_value is None else str(pipe_value)
