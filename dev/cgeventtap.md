# CGEventTap — Use ctypes, Not PyObjC

CGEventTap callbacks **must** use the ctypes bindings in `wenzi/_cgeventtap.py`, NOT PyObjC's `Quartz.CGEventTapCreate`. PyObjC's callback bridge internally retains `CGEventRef` wrappers (CF types freed by `CFRelease`, not autorelease), accumulating ~42 MB over 7 hours. The ctypes path bypasses the bridge entirely — callbacks receive raw `c_void_p` pointers with no `CFRetain`.

## Example

```python
from wenzi import _cgeventtap as cg

def _callback(self, proxy, event_type, event, refcon):
    # event is a raw c_void_p integer — no PyObjC wrapper
    keycode = cg.CGEventGetIntegerValueField(event, cg.kCGKeyboardEventKeycode)
    flags = cg.CGEventGetFlags(event)
    # ... process ...
    return event  # pass through (active tap) or None/0 (swallow / listen-only)

def start(self):
    def _raw_cb(proxy, event_type, event, refcon):
        return self._callback(proxy, event_type, event, refcon) or 0
    self._ctypes_cb = cg.CGEventTapCallBack(_raw_cb)  # MUST store to prevent GC!
    self._tap = cg.CGEventTapCreate(
        cg.kCGSessionEventTap, cg.kCGHeadInsertEventTap,
        cg.kCGEventTapOptionListenOnly, mask, self._ctypes_cb, None,
    )
    # ... CFRunLoop setup via cg.CFMachPortCreateRunLoopSource, etc.
```

## Key Rules

- **Store `self._ctypes_cb`** — if the ctypes callback is garbage collected, the tap segfaults
- Synthetic events from `cg.CGEventCreateKeyboardEvent` must be `cg.CFRelease`'d after posting
- The `_raw_cb` trampoline converts `None` returns to `0` (ctypes `c_void_p` cannot handle `None`)
- Set `self._ctypes_cb = None` in `stop()` only after the tap is disabled and the run loop is stopped

## Reference Implementations

- `hotkey.py` — `_QuartzAllKeysListener`, `TapHotkeyListener`, `KeyRemapListener`
- `snippet_expander.py` — `SnippetExpander`
