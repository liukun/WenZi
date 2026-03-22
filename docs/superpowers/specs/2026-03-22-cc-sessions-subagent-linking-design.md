# CC-Sessions: Subagent Session Linking

## Overview

Add clickable links in the session viewer to navigate from a parent session into subagent sessions. Each subagent session opens in an independent viewer panel with full functionality (info bar, stats, outline, conversation flow), plus a "Parent Session" link to navigate back.

## Background

Claude Code stores subagent sessions alongside the parent:
```
~/.claude/projects/{project}/
  {session_id}.jsonl              # parent session
  {session_id}/subagents/
    agent-{agentId}.jsonl         # subagent session
    agent-{agentId}.meta.json     # metadata (agentType)
```

The parent session's JSONL contains Agent tool_use calls, and the corresponding tool_result includes an `agentId: {hex_id}` string that maps to the subagent file name.

Subagent sessions are NOT listed in the launcher's session list — they are only accessible through the parent session viewer.

## Data Flow

### agentId Extraction (viewer.html JS)

In `computeStats()`, extend subagent records:
- Record `toolUseId` (the Agent tool_use `id`)
- After stats computation, iterate `globalResultMap` to find each Agent's tool_result
- Extract agentId via regex `agentId:\s*([a-f0-9]+)` from tool_result text content
- Associate agentId with the subagent record

### File Existence Check

On viewer load, after extracting all agentIds, call:
```js
const existsMap = await wz.call("check_subagent_exists", {
  parent_file_path: sessionFilePath,
  agent_ids: [id1, id2, ...]
});
// Returns: { "ae2a981d3905efa69": true, "bf3c...": false }
```

Only subagents with `existsMap[agentId] === true` are rendered as clickable links. Others remain plain text.

### Subagent JSONL Path Resolution (Python)

Given `parent_file_path` and `agent_id`:
```
parent_dir  = dirname(parent_file_path)
session_id  = stem(parent_file_path)
subagent_path = parent_dir / session_id / "subagents" / f"agent-{agent_id}.jsonl"
```

## Python Bridge API (init_plugin.py)

### `check_subagent_exists(parent_file_path, agent_ids)`

- For each agent_id, resolve subagent path and check file existence
- Returns `{agent_id: bool}` map

### `open_subagent(parent_file_path, agent_id, description)`

1. Resolve subagent JSONL path
2. Open a new `wz.ui.webview_panel()` with viewer.html
3. Pass parameters to viewer:
   - `file_path` = subagent JSONL path
   - `parent_file_path` = parent session JSONL path
   - `agent_id` = agentId
4. Panel title: `"Subagent: {description}"`

### `open_parent_session(parent_file_path)`

1. Close current subagent viewer panel
2. If parent session viewer is already open → focus it
3. If not → open a new viewer panel for the parent session

## Viewer UI Changes (viewer.html)

### Info Bar — Parent Link (subagent mode only)

When `parent_file_path` is present in viewer params, render at the left of info bar:

```
[← Parent Session]  Project: VoiceText  Branch: main  ...
```

Click calls `wz.call("open_parent_session", { parent_file_path })`.

### Stats Panel — Subagents Card

Each subagent description line becomes a clickable link (when agentId exists and file confirmed):

```
🔗 Explore recording stop logic  (haiku)     ← clickable
   Some other task  (opus)                    ← plain text if file missing
```

Click calls `wz.call("open_subagent", { parent_file_path, agent_id, description })`.

### Conversation Flow — Agent Tool Block

In `createToolSingle` for Agent tool_use, when agentId is available and file exists, add a `[View Session]` button in the tool-header (right side, before the arrow):

```
🤖 Agent  "Explore recording stop logic"  [View Session]  ▶
```

- Click on `[View Session]` calls `open_subagent` — must NOT trigger the tool block expand/collapse toggle
- `event.stopPropagation()` on the button to prevent header click propagation

### Stats Summary Line

No change — `"3 subagents"` text remains as-is.

## Edge Cases

### agentId extraction failure
Old Claude Code sessions may not include `agentId:` in tool_result. These subagents have `agentId = null`, all link positions fall back to plain text.

### File not found
Handled by `check_subagent_exists` at load time. Non-existent subagent files are rendered as non-clickable text.

### Multiple panels
Multiple subagent viewers can be open simultaneously. Each is independent with its own title.

### Nested subagents
If a subagent itself spawns sub-subagents, the design works recursively — the subagent viewer will also render `[View Session]` links for its own Agent tool calls, resolving paths relative to the subagent's own JSONL location. However, Claude Code currently stores all subagents flat under the parent session's `subagents/` directory, so nested resolution needs to account for this: sub-subagent files would still live under the original parent's subagents dir.

## Files Changed

| File | Change |
|------|--------|
| `plugins/cc_sessions/viewer.html` | agentId extraction, subagent link rendering, parent link, View Session button, bridge calls |
| `plugins/cc_sessions/init_plugin.py` | New bridge handlers: `check_subagent_exists`, `open_subagent`, `open_parent_session` |

## Not Changed

- `scanner.py` — no scanning of subagent files
- `cache.py` — cache structure unchanged
- `preview.py` — launcher preview unchanged
- Launcher session list — subagents not listed
