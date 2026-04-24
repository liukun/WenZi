"""Tests for wenzi.scripting.script_registry — registry, parser, dispatch."""

from __future__ import annotations

import asyncio

import pytest

from wenzi.scripting import script_registry as sr

pytestmark = pytest.mark.usefixtures("isolate_script_registry")


class TestRegister:
    def test_register_and_lookup(self):
        sr.register("test_one", lambda: "ok")
        assert sr.lookup("test_one")() == "ok"

    def test_register_rejects_empty_name(self):
        with pytest.raises(ValueError, match="non-empty"):
            sr.register("", lambda: "x")

    def test_register_rejects_duplicate(self):
        sr.register("test_dup", lambda: "a")
        with pytest.raises(ValueError, match="already registered"):
            sr.register("test_dup", lambda: "b")

    def test_register_builtin_is_idempotent(self):
        sr._register_builtin("test_ow", lambda: "a")
        sr._register_builtin("test_ow", lambda: "b")
        assert sr.lookup("test_ow")() == "b"

    def test_register_builtin_rejects_async(self):
        async def coro():
            return "x"

        with pytest.raises(TypeError, match="must be sync"):
            sr._register_builtin("test_async_builtin", coro)

    def test_register_rejects_async(self):
        async def coro():
            return "x"

        with pytest.raises(TypeError, match="async"):
            sr.register("test_async", coro)

    def test_register_does_not_inspect_loop_dependent(self):
        # Functions returning a coroutine are NOT detected as async unless
        # they are themselves coroutine functions — that is intentional.
        def lazy():
            return asyncio.sleep(0)  # returns coroutine, but `lazy` is sync

        sr.register("test_lazy", lazy)
        assert sr.lookup("test_lazy") is lazy

    def test_unregister_idempotent(self):
        sr.unregister("never_registered")  # no error
        sr.register("test_un", lambda: "x")
        sr.unregister("test_un")
        assert sr.lookup("test_un") is None


class TestSplitChain:
    def test_no_separator(self):
        assert sr._split_chain("foo") == ["foo"]

    def test_simple_chain(self):
        assert sr._split_chain("a|b|c") == ["a", "b", "c"]

    def test_strips_whitespace(self):
        assert sr._split_chain(" a | b | c ") == ["a", "b", "c"]

    def test_pipe_inside_string_literal(self):
        assert sr._split_chain('date("a|b")|upper') == [
            'date("a|b")',
            "upper",
        ]

    def test_pipe_inside_paren(self):
        assert sr._split_chain("foo(1, 2)|bar") == ["foo(1, 2)", "bar"]

    def test_escaped_quote_in_string(self):
        assert sr._split_chain(r'foo("a\"b|c")|bar') == [
            r'foo("a\"b|c")',
            "bar",
        ]

    def test_unterminated_string_raises(self):
        with pytest.raises(ValueError, match="unterminated string"):
            sr._split_chain('foo("abc')


class TestParseCall:
    def test_bare_name(self):
        assert sr._parse_call("foo") == ("foo", [], {})

    def test_namespaced_name(self):
        assert sr._parse_call("my-plugin.timestamp") == (
            "my-plugin.timestamp",
            [],
            {},
        )

    def test_no_args_with_parens(self):
        assert sr._parse_call("foo()") == ("foo", [], {})

    def test_positional_args(self):
        assert sr._parse_call('replace("a", "b")') == (
            "replace",
            ["a", "b"],
            {},
        )

    def test_keyword_args(self):
        assert sr._parse_call('date(fmt="%Y")') == ("date", [], {"fmt": "%Y"})

    def test_mixed_args(self):
        name, args, kwargs = sr._parse_call('foo(1, "x", key=2)')
        assert (name, args, kwargs) == ("foo", [1, "x"], {"key": 2})

    def test_list_dict_literals(self):
        name, args, kwargs = sr._parse_call("foo([1, 2], opts={'a': 1})")
        assert (name, args, kwargs) == ("foo", [[1, 2]], {"opts": {"a": 1}})

    def test_negative_number(self):
        name, args, _ = sr._parse_call("foo(-3)")
        assert args == [-3]

    def test_rejects_identifier_arg(self):
        with pytest.raises(ValueError, match="non-literal"):
            sr._parse_call("foo(bar)")

    def test_rejects_expression_arg(self):
        with pytest.raises(ValueError, match="non-literal"):
            sr._parse_call("foo(1 + 1)")

    def test_rejects_attribute(self):
        with pytest.raises(ValueError, match="non-literal"):
            sr._parse_call("foo(os.environ)")

    def test_rejects_double_star_kwargs(self):
        with pytest.raises(ValueError, match=r"\*\*kwargs"):
            sr._parse_call("foo(**{'a': 1})")

    def test_rejects_invalid_name(self):
        with pytest.raises(ValueError, match="invalid script call"):
            sr._parse_call("1foo")

    def test_rejects_empty_segment(self):
        with pytest.raises(ValueError, match="empty"):
            sr._parse_call("")


class TestDispatch:
    def test_no_arg_call(self):
        sr.register("hello", lambda: "world")
        assert sr.dispatch("hello") == "world"

    def test_call_with_args(self):
        sr.register("greet", lambda name: f"hi {name}")
        assert sr.dispatch('greet("alice")') == "hi alice"

    def test_chain_pipes_first_arg(self):
        sr.register("src", lambda: "abc")
        sr.register("upper", lambda s: s.upper())
        assert sr.dispatch("src|upper") == "ABC"

    def test_chain_with_extra_args_after_pipe(self):
        sr.register("src", lambda: "hello")
        sr.register("rep", lambda s, old, new: s.replace(old, new))
        assert sr.dispatch('src|rep("l", "L")') == "heLLo"

    def test_long_chain(self):
        sr.register("a", lambda: "x")
        sr.register("b", lambda s: s + "y")
        sr.register("c", lambda s: s + "z")
        assert sr.dispatch("a|b|c") == "xyz"

    def test_unknown_name_raises_keyerror(self):
        with pytest.raises(KeyError):
            sr.dispatch("does_not_exist")

    def test_non_string_return_coerced(self):
        sr.register("num", lambda: 42)
        assert sr.dispatch("num") == "42"

    def test_none_return_becomes_empty_string(self):
        sr.register("nothing", lambda: None)
        assert sr.dispatch("nothing") == ""

    def test_kwargs_not_passed_to_pipe_target(self):
        sr.register("src", lambda: "hi")
        sr.register("tag", lambda s, level="info": f"[{level}] {s}")
        assert sr.dispatch('src|tag(level="warn")') == "[warn] hi"

    def test_script_exception_propagates(self):
        def boom():
            raise RuntimeError("kaboom")

        sr.register("boom", boom)
        with pytest.raises(RuntimeError, match="kaboom"):
            sr.dispatch("boom")
