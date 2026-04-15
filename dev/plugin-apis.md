# Plugin APIs

## Secret Storage — `wz.keychain`

Use `wz.keychain` (not `wz.store`) for sensitive data. `wz.store` is plaintext JSON; `wz.keychain` encrypts with AES-256-GCM.

```python
wz.keychain.set("raindrop.token", token)   # → bool
token = wz.keychain.get("raindrop.token")   # → str or None
wz.keychain.delete("raindrop.token")
wz.keychain.keys()
```

Architecture: AES-256-GCM master key in macOS Keychain (`scripting.vault.master_key`), encrypted data in `~/.local/share/WenZi/keychain.json`. Auto-generated on first access. When Keychain unavailable: `get()` → None, `set()` → False.

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
