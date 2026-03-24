# Asyncio 迁移计划：统一协程并发模型

## 目标

将当前 "主线程 + 大量临时 worker 线程 + 临时 event loop" 的并发模型，迁移到 **单一持久 asyncio 事件循环 + 协程** 模型。

**核心收益：**
- 消除 RecordingController 中的 6 个同步原语（`_recording_started`, `_cancel_delayed`, `_release_done`, `_release_lock`, `_streaming_lock`, `_busy_token`）
- 消除 9 处 `asyncio.new_event_loop()` + `run_until_complete()` + `close()`
- 用线性协程替代回调碎片，流程可读性大幅提升
- 取消/超时从手动管理变为 asyncio 内建支持

## 架构概览

```
Hotkey Thread (CGEventTap)
  │  call_soon_threadsafe / run_coroutine_threadsafe
  ▼
Asyncio Thread (单一持久 event loop)          ──→    Main Thread (NSRunLoop)
  ├─ RecordingFlow 协程                               ├─ UI 更新 (callAfter)
  │   ├─ await asyncio.sleep(0.35)                     └─ 纯展示，不持有业务状态
  │   ├─ await run_in_executor(recorder.start)
  │   ├─ await action_queue.get()  ← 统一信号队列
  │   ├─ await run_in_executor(transcribe)
  │   └─ async for chunk in enhance_stream()
  ├─ EnhanceController 协程
  │   └─ async for chunk in enhance_stream()
  ├─ VocabBuilder 协程
  │   └─ await builder.build()
  └─ ModelController 协程
      └─ await verify_provider()

Audio Thread (sounddevice callback)
  └─ queue.Queue → Recorder（不变）
```

**原则：**
- asyncio 线程持有所有业务状态，单线程内无竞态
- 阻塞 I/O（recorder.start/stop、transcribe）通过 `run_in_executor` 执行
- AsyncOpenAI 原生运行，无需临时 event loop
- 主线程只做 UI 渲染，通过 `callAfter` 接收指令
- hotkey 线程只做信号投递，不执行任何业务逻辑

---

## Phase 0：基础设施 — AsyncEventLoop 单例

### 0.1 新建 `src/wenzi/async_loop.py`

提供全局单例 asyncio 事件循环，运行在专用守护线程上。

```python
"""Singleton asyncio event loop running on a dedicated daemon thread."""

import asyncio
import threading
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_started = threading.Event()


def get_loop() -> asyncio.AbstractEventLoop:
    """Return the shared event loop, starting the thread on first call."""
    global _loop, _thread
    if _loop is not None and _loop.is_running():
        return _loop
    _loop = asyncio.new_event_loop()
    _thread = threading.Thread(target=_run, daemon=True, name="asyncio-loop")
    _thread.start()
    _started.wait()
    return _loop


def _run() -> None:
    asyncio.set_event_loop(_loop)
    _started.set()
    _loop.run_forever()


def submit(coro: Coroutine[Any, Any, T]) -> asyncio.Future[T]:
    """Submit a coroutine to the shared loop (thread-safe)."""
    return asyncio.run_coroutine_threadsafe(coro, get_loop())


def call_soon(callback, *args) -> None:
    """Schedule a callback on the shared loop (thread-safe)."""
    get_loop().call_soon_threadsafe(callback, *args)


async def shutdown() -> None:
    """Gracefully shut down the loop. Called during app quit."""
    loop = get_loop()
    # Cancel all pending tasks
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await loop.shutdown_asyncgens()
    loop.stop()
```

### 0.2 测试

- 验证 `get_loop()` 幂等性
- 验证 `submit()` 从多线程调用的安全性
- 验证 `shutdown()` 正确取消所有 pending task

---

## Phase 1：RecordingController → RecordingFlow 协程化

这是改动最大、收益最高的部分。当前 `recording_controller.py` 约 1100 行，涉及 6 个同步原语和 15+ 处线程创建。

### 1.1 定义 Action 信号枚举

```python
# src/wenzi/controllers/recording_flow.py (新文件)

import enum

class Action(enum.Enum):
    RELEASE = "release"
    CANCEL = "cancel"
    RESTART = "restart"
    MODE_PREV = "mode_prev"
    MODE_NEXT = "mode_next"
    PREVIEW_HISTORY = "preview_history"
```

### 1.2 RecordingFlow 核心结构

```python
class RecordingFlow:
    def __init__(self, app: WenZiApp):
        self._app = app
        self._loop = async_loop.get_loop()
        self._actions: asyncio.Queue[Action] = asyncio.Queue()
        self._current_task: asyncio.Task | None = None
        # 非协程逻辑（mode 管理等）从 RecordingController 平移
        self._prefer_mode: str | None = None
        self._saved_mode: tuple | None = None
        self._input_context = None

    @property
    def is_busy(self) -> bool:
        return self._current_task is not None and not self._current_task.done()
```

### 1.3 hotkey 线程入口

```python
    # --- hotkey 线程调用（线程安全） ---

    def on_press(self, key_name: str = ""):
        async_loop.submit(self._handle_press(key_name))

    def send_action(self, action: Action):
        self._loop.call_soon_threadsafe(self._actions.put_nowait, action)
```

### 1.4 `_handle_press` — 会话入口

```python
    async def _handle_press(self, key_name: str):
        if self.is_busy:
            return

        app = self._app

        # 配置检查（需要回主线程弹窗）
        if app._config_degraded:
            callAfter(app._show_config_error_alert)
            return
        if not app._voice_input_available:
            # 语音初始化仍在主线程弹窗，保持原有逻辑
            callAfter(self._try_enable_voice_input)
            return

        # 捕获输入上下文（需要在用户目标 app 还在前台时）
        # capture_input_context 调用 AX API，需在主线程或允许跨线程
        self._input_context = await self._loop.run_in_executor(
            None, lambda: capture_input_context(ic_level)
        )

        # 处理 prefer_mode
        self._restore_mode()
        self._apply_prefer_mode_if_needed(key_name)

        # 清空残留 action
        while not self._actions.empty():
            self._actions.get_nowait()

        self._current_task = asyncio.create_task(
            self._recording_session(key_name)
        )
```

### 1.5 `_recording_session` — 完整会话协程

这是核心。整个 press → delay → record → release → transcribe → enhance → output
流程在一个协程中线性表达。

```python
    async def _recording_session(self, key_name: str):
        app = self._app
        try:
            # ① 播放提示音 + 延迟
            callAfter(app._set_status, "statusbar.status.recording")
            callAfter(app._sound_manager.play, "start")
            callAfter(self._show_indicator_gray)
            callAfter(self._show_mode_on_indicator)

            if app._sound_manager.enabled:
                # 延迟期间监听 cancel/release
                action = await self._wait_action(
                    Action.RELEASE, Action.CANCEL,
                    timeout=self._DELAYED_START_SECS,
                )
                if action == Action.CANCEL:
                    return
                if action == Action.RELEASE:
                    # 提示音还没放完就松了
                    return
                # None = timeout = 正常继续

            # ② 启动录音（阻塞 → executor）
            dev_name = await self._loop.run_in_executor(
                None, app._recorder.start
            )
            callAfter(self._set_indicator_active, dev_name)

            # 启动流式转写（如果支持）
            streaming = await self._start_streaming_if_supported()

            # ③ 录音中 — 等待用户操作
            max_sec = app._config.get("audio", {}).get(
                "max_recording_seconds", 120
            )
            action = await self._wait_action(
                Action.RELEASE, Action.CANCEL, Action.RESTART,
                Action.PREVIEW_HISTORY,
                timeout=max_sec,
            )

            if action == Action.CANCEL:
                await self._stop_recording_and_streaming(streaming)
                return

            if action == Action.RESTART:
                await self._stop_recording_and_streaming(streaming)
                raise _RestartSession(key_name)

            if action == Action.PREVIEW_HISTORY:
                await self._stop_recording_and_streaming(streaming)
                callAfter(app._preview_controller.on_show_last_preview)
                return

            # action is RELEASE or None (timeout)

            # ④ 停止录音
            if streaming:
                self._stop_streaming()
            wav_data = await self._loop.run_in_executor(
                None, app._recorder.stop
            )
            callAfter(self._stop_indicator, True)

            if not wav_data:
                return

            audio_duration = self._record_audio_duration(wav_data)

            # ⑤ 转写
            if streaming:
                text = await self._loop.run_in_executor(
                    None, app._transcriber.stop_streaming
                )
            else:
                callAfter(app._set_status, "statusbar.status.transcribing")
                hotwords, _ = app._build_dynamic_hotwords()
                text = await self._loop.run_in_executor(
                    None, lambda: app._transcriber.transcribe(
                        wav_data, hotwords=hotwords
                    )
                )

            if not text or not text.strip():
                callAfter(app._set_status, "statusbar.status.empty")
                return

            asr_text = text.strip()

            # ⑥ 分流：preview 模式 vs direct 模式
            if app._preview_enabled:
                await self._do_preview_flow(asr_text, wav_data, audio_duration)
            else:
                await self._do_direct_flow(asr_text, wav_data, audio_duration)

        except _RestartSession as rs:
            # 重新开始：创建新 task
            self._current_task = asyncio.create_task(
                self._recording_session(rs.key_name)
            )
        except asyncio.CancelledError:
            # 外部强制取消（如 app 退出）
            if app._recorder.is_recording:
                app._recorder.stop()
            callAfter(self._reset_to_idle)
        finally:
            if not isinstance(
                self._current_task, asyncio.Task
            ) or self._current_task.done():
                callAfter(self._reset_to_idle)
```

### 1.6 `_wait_action` — 统一信号等待

```python
    async def _wait_action(
        self, *expected: Action, timeout: float,
    ) -> Action | None:
        """等待期望的 action，就地处理 inline action（如切模式）。
        返回匹配的 action，超时返回 None。"""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return None
            try:
                action = await asyncio.wait_for(
                    self._actions.get(), timeout=remaining
                )
            except asyncio.TimeoutError:
                return None
            if action in expected:
                return action
            # inline action（不中断主流程）
            self._handle_inline_action(action)

    def _handle_inline_action(self, action: Action):
        if action == Action.MODE_PREV:
            self._navigate_mode(-1)
        elif action == Action.MODE_NEXT:
            self._navigate_mode(+1)
```

### 1.7 `_do_direct_flow` — 直出模式（LLM 原生 async）

```python
    async def _do_direct_flow(self, asr_text: str, wav_data, audio_duration: float):
        app = self._app
        use_enhance = bool(app._enhancer and app._enhancer.is_active)

        # 显示 overlay
        callAfter(self._show_streaming_overlay, asr_text, use_enhance)

        text = asr_text
        enhanced_text = None

        if use_enhance:
            callAfter(app._set_status, "statusbar.status.enhancing")

            # 原生 async for — 不需要 new_event_loop！
            collected = []
            async for chunk, usage, is_thinking in app._enhancer.enhance_stream(
                asr_text, input_context=self._input_context
            ):
                # 检查是否被 cancel（通过 action queue）
                if not self._actions.empty():
                    peek = self._actions.get_nowait()
                    if peek == Action.CANCEL:
                        app._enhancer.cancel_stream()
                        callAfter(app._streaming_overlay.close)
                        return
                    # 其他 action 放回去
                    self._actions.put_nowait(peek)

                if is_thinking and chunk:
                    callAfter(app._streaming_overlay.append_thinking_text, chunk)
                elif chunk:
                    collected.append(chunk)
                    callAfter(app._streaming_overlay.append_text, chunk)

            text = "".join(collected).strip() or asr_text
            enhanced_text = text

        # 输出
        callAfter(type_text, text.strip())
        callAfter(app._set_status, "statusbar.status.ready")
        self._log_conversation(asr_text, enhanced_text, text)
```

### 1.8 `_do_preview_flow` — Preview 模式

Preview 模式下转写和增强由 `EnhanceController` 管理（Phase 2 处理），
这里只需把 `app._do_transcribe_with_preview()` 投递过去。

```python
    async def _do_preview_flow(self, asr_text, wav_data, audio_duration):
        app = self._app
        use_enhance = bool(app._enhancer and app._enhancer.is_active)
        # Preview 面板的更新由 EnhanceController 处理
        # 这里只启动流程
        callAfter(
            app._do_transcribe_with_preview,
            asr_text=asr_text,
            use_enhance=use_enhance,
            audio_duration=audio_duration,
            wav_data=wav_data,
        )
```

### 1.9 流式转写集成

```python
    async def _start_streaming_if_supported(self) -> bool:
        """启动流式转写，返回是否成功。"""
        app = self._app
        if not app._transcriber.supports_streaming:
            return False
        try:
            partial_queue: asyncio.Queue[str] = asyncio.Queue()

            def _on_partial(text: str, is_final: bool):
                # 从转写线程投递到 asyncio 线程
                self._loop.call_soon_threadsafe(partial_queue.put_nowait, text)

            app._transcriber.start_streaming(_on_partial)
            app._recorder.set_on_audio_chunk(app._transcriber.feed_audio)
            self._partial_queue = partial_queue

            callAfter(self._show_live_overlay)

            # 启动后台 task 消费 partial 结果并更新 UI
            self._partial_consumer = asyncio.create_task(
                self._consume_partials(partial_queue)
            )
            return True
        except Exception:
            logger.exception("Failed to start streaming")
            return False

    async def _consume_partials(self, q: asyncio.Queue[str]):
        """持续消费流式转写的 partial 结果并更新 overlay。"""
        try:
            while True:
                text = await q.get()
                callAfter(self._update_live_overlay, text)
        except asyncio.CancelledError:
            pass
```

### 1.10 Level Polling 改用 asyncio 循环

```python
    async def _poll_level(self):
        """录音期间轮询音量并更新 indicator。"""
        app = self._app
        try:
            while True:
                level = app._recorder.current_level
                callAfter(app._recording_indicator.update_level, level)
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            pass
```

在 `_recording_session` 中启动和取消：

```python
    # 启动录音后
    level_task = asyncio.create_task(self._poll_level())

    # 停止录音时
    level_task.cancel()
```

### 1.11 hotkey.py 适配

修改 `MultiHotkeyListener._handle_press` 和 `_handle_release`：

**之前**：每个 action 都 `threading.Thread(target=..., daemon=True).start()`

**之后**：

```python
# press
elif action == "press":
    self._recording_flow.on_press(name)
    # 不再起线程

# release
elif action == "release":
    self._recording_flow.send_action(Action.RELEASE)

# restart
elif action == "restart":
    self._recording_flow.send_action(Action.RESTART)
    return True

# cancel
elif action == "cancel":
    self._cancel_requested = True
    self._recording_flow.send_action(Action.CANCEL)
    return True

# mode_prev/next
elif action == "mode_prev":
    self._recording_flow.send_action(Action.MODE_PREV)
    return True
```

`_cancel_requested` 逻辑保留（用于在 cancel 后抑制 release），
但 release 侧也简化——如果协程已经结束/重启，多一个 RELEASE 信号会被
`_handle_press` 的 `empty()` 清掉。

### 1.12 移除的代码

从 `RecordingController` 中删除：
- `_recording_started: threading.Event`
- `_cancel_delayed: threading.Event`
- `_release_done: bool`
- `_release_lock: threading.Lock`
- `_streaming_lock: threading.Lock`
- `_streaming_active: bool`
- `_busy_token: int` / `_claim_busy()` / `_release_busy()`
- `_recording_watchdog: threading.Timer` / `_start_recording_watchdog()` / `_cancel_recording_watchdog()`
- `_delayed_thread: threading.Thread`
- `_level_poll_stop: threading.Event`（从 app.py 也移除）
- 所有 `threading.Thread(target=..., daemon=True).start()` 调用

从 `app.py` 中删除：
- `self._recording_started = threading.Event()`
- `self._level_poll_stop: threading.Event | None = None`

### 1.13 `app._busy` 属性改造

```python
# 之前：手动管理的 bool
app._busy = True / False

# 之后：委托给 RecordingFlow
@property
def _busy(self) -> bool:
    return self._recording_flow.is_busy
```

### 1.14 测试策略

- 单元测试 `RecordingFlow`：mock `app`，直接 `await` 各协程方法
- 测试 action 信号：`flow.send_action(Action.CANCEL)` 在协程各阶段的行为
- 测试超时：mock sleep 验证 watchdog 等效行为
- 测试 restart：验证 `_RestartSession` 正确重启
- 测试 cancel 在各阶段（delay 中、录音中、转写中、增强中）的行为
- 不再需要 `_delayed_thread.join()` 等竞态敏感的断言

---

## Phase 2：EnhanceController 协程化

### 2.1 `run()` 方法改为提交协程

```python
# 之前
def run(self, asr_text, request_id, ...):
    threading.Thread(target=_enhance, daemon=True).start()

# 之后
def run(self, asr_text, request_id, ...):
    if self._current_task and not self._current_task.done():
        self._current_task.cancel()
    self._current_task = async_loop.submit(
        self._run_async(asr_text, request_id, ...)
    )
```

### 2.2 `_run_single` / `_run_chain` 去掉临时 event loop

```python
# 之前
def _run_single(self, ...):
    loop = asyncio.new_event_loop()
    async def _stream():
        async for chunk, ... in enhancer.enhance_stream(...):
            ...
    loop.run_until_complete(_stream())
    loop.close()

# 之后：直接是 async 方法
async def _run_single(self, ...):
    async for chunk, ... in self._enhancer.enhance_stream(...):
        ...
```

### 2.3 取消改造

```python
# 之前：threading.Event
cancel_event = threading.Event()
self._cancel_event = cancel_event
# 检查: if cancel_event.is_set(): ...

# 之后：asyncio.Task.cancel()
def cancel(self):
    if self._current_task and not self._current_task.done():
        self._current_task.cancel()
```

### 2.4 影响范围

- `enhance_controller.py`：`_run_single()`, `_run_chain()` 从同步改 async
- `recording_controller.py`：`_run_direct_single_stream()`, `_run_direct_chain_stream()` 删除（Phase 1 中已被 `_do_direct_flow` 替代）
- 涉及文件：`enhance_controller.py`

---

## Phase 3：enhancer.py 清理

### 3.1 移除 `asyncio.Event` 取消机制

```python
# 删除
self._cancel_event = asyncio.Event()

def cancel_stream(self):
    self._cancel_event.set()
```

`enhance_stream()` 内部不再检查 `_cancel_event`。取消由调用方的
`task.cancel()` 驱动——`CancelledError` 会在 `await asyncio.wait_for(aiter.__anext__(), ...)` 处抛出，自然中断流。

### 3.2 移除 `_active_stream` 追踪

```python
# 删除
self._active_stream = stream
# ...
self._active_stream = None
```

流的生命周期由协程的 try/finally 自然管理。

### 3.3 客户端生命周期

- `AsyncOpenAI` 客户端在持久 event loop 上运行，连接池天然复用
- `remove_provider()` 中的 fallback loop 逻辑简化：
  ```python
  # 之前：尝试 get_running_loop，失败则 new_event_loop
  # 之后：直接提交到共享 loop
  async_loop.submit(client.close())
  ```
- `close()` 在 app 退出时调用：`await enhancer.close()`

### 3.4 影响范围

- `enhancer.py`：`enhance_stream()` 简化，移除 `_cancel_event`/`_active_stream`
- `enhancer.py`：`remove_provider()` 简化
- `app.py`：`_on_quit_app()` 中的 shutdown 逻辑简化

---

## Phase 4：其他 asyncio 消费者迁移

### 4.1 `model_controller.py` — verify_provider

```python
# 之前
def _verify_in_thread(self, ...):
    loop = asyncio.new_event_loop()
    err = loop.run_until_complete(enhancer.verify_provider(...))
    loop.close()

# 之后
async def _verify(self, ...):
    err = await self._app._enhancer.verify_provider(...)
    callAfter(self._on_verify_done, err)

def verify(self, ...):
    async_loop.submit(self._verify(...))
```

### 4.2 `auto_vocab_builder.py` — 词库构建

```python
# 之前
def _build(self):
    loop = asyncio.new_event_loop()
    summary = loop.run_until_complete(builder.build(...))
    loop.close()

# 之后
async def _build(self):
    summary = await builder.build(...)
    ...

def trigger_build(self, ...):
    async_loop.submit(self._build())
```

### 4.3 `enhance_mode_controller.py` — 词库构建 UI

同上模式，提交到共享 loop。

### 4.4 `app.py` — 退出清理

```python
# 之前
def _on_quit_app(self, sender):
    loop = asyncio.new_event_loop()
    loop.run_until_complete(self._enhancer.close())
    loop.close()

# 之后
def _on_quit_app(self, sender):
    future = async_loop.submit(self._shutdown())
    future.result(timeout=5)  # 同步等待，最多 5s

async def _shutdown(self):
    if self._enhancer:
        await self._enhancer.close()
    await async_loop.shutdown()
```

---

## Phase 5：测试迁移

### 5.1 测试辅助工具

新建 `tests/helpers/async_test.py`：

```python
import asyncio

def run_async(coro):
    """在测试中运行协程。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
```

或者使用 `pytest-asyncio` 的 `@pytest.mark.asyncio` 装饰器。

### 5.2 RecordingFlow 测试重写

当前 `tests/controllers/test_recording_controller.py` 的测试需要大幅重写：

- 不再需要 `_delayed_thread.join()` — 直接 await 协程
- 不再需要 mock `threading.Event` — action queue 是确定性的
- cancel 测试：`flow.send_action(Action.CANCEL)`，然后 await task 完成
- restart 测试：send RESTART，验证新 task 创建
- 超时测试：mock recorder 延迟，验证 timeout 行为

### 5.3 EnhanceController 测试更新

- mock `enhancer.enhance_stream` 返回 async generator
- 直接 await `_run_single` / `_run_chain`
- 取消测试：`task.cancel()` 后验证清理

---

## 实施顺序和依赖

```
Phase 0: async_loop.py
   │
   ├──→ Phase 1: RecordingFlow（最大改动，最高收益）
   │       └──→ Phase 1 测试
   │
   ├──→ Phase 2: EnhanceController（依赖 Phase 0）
   │       └──→ Phase 2 测试
   │
   ├──→ Phase 3: enhancer.py 清理（依赖 Phase 1 + 2，确认无其他调用方）
   │
   ├──→ Phase 4: 其他消费者（model_controller, vocab_builder, app shutdown）
   │
   └──→ Phase 5: 测试全面更新
```

**建议一个 Phase 一个 PR**，每个 PR 保证测试通过。
Phase 1 是最核心的改动，可以独立于 Phase 2-4 上线。

---

## 风险和注意事项

### `run_in_executor` 中的阻塞调用无法被中断

`recorder.start()` 如果阻塞在权限弹窗或 PortAudio 初始化，`task.cancel()` 只能在
`await` resume 时生效，executor 线程仍在运行。需要在 `except CancelledError`
中检查并清理：

```python
except asyncio.CancelledError:
    if app._recorder.is_recording:
        app._recorder.stop()
```

这和当前行为一致（当前的 orphan 检查逻辑做的就是这件事）。

### `capture_input_context` 需要在目标 app 前台时调用

当前在 `on_hotkey_press` 中同步调用。迁移后通过 `run_in_executor` 可能有
微小延迟。需要验证 AX API 在后台线程调用的可靠性。如果有问题，可以在
hotkey 回调中同步捕获，作为参数传给 `on_press`。

### CGEventTap 回调不能阻塞

当前已经通过 `threading.Thread` 避免阻塞。迁移后用 `call_soon_threadsafe` /
`run_coroutine_threadsafe` 同样是非阻塞的。

### 流式转写的 `feed_audio` 回调

`recorder._on_audio_chunk` 回调在 sounddevice 音频线程上执行，直接调用
`transcriber.feed_audio()`。这部分不经过 asyncio 线程，保持不变。

### `AppHelper.callAfter` vs `NSOperationQueue.mainQueue()`

本计划保持使用 `callAfter`，它在当前代码中已经过充分验证。
如果需要返回值或取消能力，可以后续考虑切换。

### 渐进式迁移的兼容性

Phase 1 只改 RecordingController。在 Phase 2 完成前，EnhanceController
仍然用旧的 `threading.Thread` + `asyncio.new_event_loop()` 模式。
两者可以共存——RecordingFlow 的 `_do_preview_flow` 通过 callAfter 调用
app 层方法，不直接依赖 EnhanceController 的内部实现。

---

## 消除的复杂度汇总

| 移除 | 数量 | 替代 |
|------|------|------|
| `asyncio.new_event_loop()` + `run_until_complete()` + `close()` | 9 处 | 共享 loop，直接 async/await |
| `threading.Thread(daemon=True).start()` | ~20 处 | `async_loop.submit()` 或 `create_task()` |
| `threading.Lock` | 5 个 | 无需（asyncio 单线程） |
| `threading.Event` | 7 个 | `asyncio.Queue` 统一信号 / `task.cancel()` |
| `threading.Timer` | 3 个 | `asyncio.wait_for` / `asyncio.sleep` |
| 手动 `_busy_token` 引用计数 | 1 套 | `task.done()` 属性 |
| orphan 检查逻辑 | 1 处 | 协程 finally 自然清理 |
| `_cancel_requested` flag | 1 处 | 协程结束后 action 自然丢弃 |
