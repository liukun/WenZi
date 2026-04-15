# 词库命中追踪

Feature is **implemented**. This doc preserves the design decisions and architecture for reference.

## 四维追踪模型

将原有的单一 `hit_count` 拆分为四个独立维度：

| 维度 | 含义 | 检测条件 |
|------|------|---------|
| `asr_miss` | ASR 输出了错误形式（variant） | `variant in asr_text` |
| `asr_hit` | ASR 输出了正确形式（term） | `term in asr_text`（且 variant 不在 asr_text 中） |
| `llm_hit` | LLM 增强后包含正确形式 | `variant in asr_text AND term in enhanced_text` |
| `llm_miss` | LLM 增强后仍未纠正 | `variant in asr_text AND term NOT in enhanced_text` |

维度关系：`asr_miss` 与 `asr_hit` 互斥；`llm_hit` 与 `llm_miss` 互斥且仅在 `asr_miss` 时计数。恒等式：`asr_miss = llm_hit + llm_miss`。

## 存储：SQLite 两张表

```sql
-- 词条主表
CREATE TABLE vocab_entry (
    id            INTEGER PRIMARY KEY,
    term          TEXT NOT NULL,
    variant       TEXT NOT NULL,
    source        TEXT NOT NULL,          -- 'asr' | 'llm' | 'user'
    frequency     INTEGER DEFAULT 1,
    first_seen    TEXT NOT NULL,
    last_updated  TEXT NOT NULL,
    app_bundle_id TEXT DEFAULT '',
    asr_model     TEXT DEFAULT '',
    llm_model     TEXT DEFAULT '',
    enhance_mode  TEXT DEFAULT '',
    UNIQUE(term, variant)
);

-- 分桶统计表
CREATE TABLE vocab_stats (
    entry_id    INTEGER NOT NULL REFERENCES vocab_entry(id) ON DELETE CASCADE,
    metric      TEXT NOT NULL,            -- 'asr_miss' | 'asr_hit' | 'llm_hit' | 'llm_miss'
    context_key TEXT NOT NULL,            -- 'asr:whisper-large-v3' | 'app:com.apple.dt.Xcode' | ...
    count       INTEGER DEFAULT 0,
    last_time   TEXT DEFAULT '',
    PRIMARY KEY (entry_id, metric, context_key)
);

CREATE INDEX idx_stats_rank ON vocab_stats(metric, context_key, count DESC);
```

上下文桶键：`asr:<model>`, `llm:<model>`, `app:<bundle_id>`

## 两阶段检测

- **阶段一**（ASR 输出后、LLM 增强前）：扫描全部词条，记录 `asr_miss` / `asr_hit`
- **阶段二**（LLM 增强后）：对阶段一的 asr_miss 词条，记录 `llm_hit` / `llm_miss`

## 注入排序

| 计数 | 高值含义 | 驱动决策 |
|------|---------|---------|
| `asr_miss` 高 | ASR 经常出错 | 优先注入 ASR 热词 |
| `asr_hit` 高 | ASR 自身能正确识别 | 可降低 ASR 注入优先级 |
| `llm_hit` 高 | LLM 能纠正 | 优先注入 LLM 词库 |
| `llm_miss` 高 | LLM 也纠正不了 | 更依赖 ASR 热词 |

冷启动回退：指定桶 → 全局汇总 → last_updated 兜底。

## UI：表格总览 + 展开详情

- 表格 ASR 列：`miss/total` 格式（如 `3/15`）
- 表格 LLM 列：`hit/total` 格式（如 `2/3`）
- 点击行展开分桶详情（按 ASR model / LLM model / App 分组）
- 筛选标签联动切换统计桶

## 实现文件

| 文件 | 作用 |
|------|------|
| `src/wenzi/enhance/vocab_db.py` | SQLite 存储层 |
| `src/wenzi/enhance/manual_vocabulary.py` | 委托 VocabDB，两阶段检测 |
| `src/wenzi/enhance/vocabulary.py` | HotwordDetail，排序选词 |
| `src/wenzi/controllers/enhance_controller.py` | 两阶段命中检测入口 |
| `src/wenzi/controllers/vocab_controller.py` | UI 数据序列化、筛选联动 |
| `src/wenzi/ui/templates/vocab_manager_web.html` | 表格列、展开详情、样式 |
