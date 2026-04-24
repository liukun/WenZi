# Plugin APIs

## Snippet Scripts — `wz.script`

Register a sync callable that snippets can invoke as a placeholder. The
returned value (cast to `str`) is substituted into the snippet text.

```python
def setup(wz):
    wz.script("timestamp", lambda: str(int(time.time())))
    wz.script("upper", lambda s: s.upper())
```

Used in snippets:

```
Hello at {my-plugin.timestamp}!
Upper: {clipboard|my-plugin.upper}
```

### Naming

Inside `setup(wz)`, the registered name is auto-prefixed with the plugin id:
`wz.script("timestamp", ...)` → `my-plugin.timestamp`. Plugins cannot
collide with each other or with built-ins (`clipboard`, `date`, `time`,
`datetime`, `unwrap`).

### Placeholder syntax

| Form | Meaning |
|------|---------|
| `{name}` | call `name()` with no arguments |
| `{name(arg, key=val)}` | call with Python literal args/kwargs |
| `{a|b}` | pipe — call `b(a())`; piped value is `b`'s first positional arg |
| `{a|b("x")|c}` | chains compose left to right |
| `{{name}}` | literal `{name}`, not expanded |

Argument values must be Python **literals**: strings, numbers, bools,
`None`, lists, dicts, tuples. Identifiers, attribute access, operators,
and lambdas are rejected at parse time. The args parser is `ast.parse`
restricted to `ast.literal_eval` — no code execution path.

### Failure modes

Unknown names, parse errors, and exceptions raised by the script all
leave the placeholder text intact (e.g. `{my.bogus}` stays literal) and
log a warning. This makes typos visible instead of silently dropping
snippet content.

### Sync only

The expander is sync (called from a CGEventTap callback and from the
chooser source list-builder). Async functions are **rejected at
registration** with `TypeError`. If a script needs IO, do the work
upfront and read a cached value, or wait until
[asyncio-migration-plan.md](asyncio-migration-plan.md) lands an async
expander.

## Secret Storage — `wz.keychain`

Use `wz.keychain` (not `wz.store`) for sensitive data. `wz.store` is plaintext JSON; `wz.keychain` stores secrets in the macOS Keychain.

```python
wz.keychain.set("raindrop.token", token)   # → bool
token = wz.keychain.get("raindrop.token")   # → str or None
wz.keychain.delete("raindrop.token")
wz.keychain.keys()
```

Architecture: All secrets serialised as a JSON dict and stored in a single macOS Keychain entry under account `secrets`. When Keychain unavailable: `get()` → None, `set()` → False.

**Note:** Separate from core `wenzi.keychain` module (`keychain_get`/`keychain_set`) which stores provider API keys directly in macOS Keychain.

## Menu API — `wz.menu`

### WenZi Menu

```python
wz.menu.list()                    # nested tree
wz.menu.list(flat=True)           # flat list with "path" field
wz.menu.trigger("Settings...")    # by title
wz.menu.trigger("Parent > Child") # by path
```

### Frontmost App Menu (Accessibility)

```python
wz.menu.app_menu()                # flat list from previous app
wz.menu.app_menu(pid=1234)        # explicit pid
wz.menu.app_menu_trigger(item)    # activate app, re-find by path, AXPress
```

Requires Accessibility permission. System Apple menu auto-excluded. `app_menu_trigger()` re-locates by path (stored `_ax_element` becomes stale on focus change).
