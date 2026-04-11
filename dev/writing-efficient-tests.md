# Writing Efficient Tests

Test suite optimized from 76s → 29s (62% reduction).

## 1. Poll, Don't Sleep

```python
def _wait_for(predicate, timeout=0.5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert predicate(), "timed out"
```

Use for any async/threaded behavior — debounce timers, background tasks, streaming.

## 2. Extract Constants, Monkeypatch in Tests

```python
# Production
class RecordingController:
    _RELEASE_WAIT_TIMEOUT = 1.0

# Test
monkeypatch.setattr(RecordingController, "_RELEASE_WAIT_TIMEOUT", 0.05)
```

## 3. Mock Heavyweight Imports via `sys.modules`

```python
with patch.dict("sys.modules", {"funasr_onnx": MagicMock()}):
    result = transcriber._load_asr()
```

For Apple frameworks in headless CI: `monkeypatch.setitem(sys.modules, "Speech", MagicMock())`

## 4. Shared `conftest.py` Fixtures

When 3+ test files share identical mock setup, use package-level `conftest.py` with `autouse=True`.

## 5. Lazy Module Imports

Use `__getattr__` in `__init__.py` for deferred imports when submodules pull in heavy frameworks.

## 6. Mock System Calls at the Boundary

Mock the wrapper function, not the framework:
```python
monkeypatch.setattr("wenzi.scripting.sources.app_source._get_app_icon_png", lambda path: None)
```

## Impact

| Technique | Savings |
|-----------|---------|
| Lazy UI imports | 5-10s collection |
| `sys.modules` mock for ML libs | 10-20s |
| conftest `autouse` for word lists | 5-8s |
| Polling instead of sleep | 0.5-1s per test |
| Monkeypatch constants | 0.5-1s per test |

## Test Safety — Never Use Real User Data Paths

Always override paths with `tmp_path` to prevent tests from touching real user data.

**Known dangerous defaults:**
- `ClipboardMonitor()` → `image_dir` defaults to `~/.config/WenZi/clipboard_images`
- `ClipboardMonitor(persist_path=...)` → real SQLite database
- `SnippetStore()` → `~/.config/WenZi/snippets`
- `KeychainAPI()` / `Vault()` → reads/writes the real macOS Keychain. Always mock `wenzi.vault._keychain_get`/`_keychain_set`

**Rule:** Check default paths before instantiating in tests. Follow existing patterns in the same file.
