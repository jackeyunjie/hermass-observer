# 模型接入目录

版本：v1.0  
日期：2026-05-28  
状态：活跃

> 用途：为 Hermass 接入不同模型或运行时提供统一模板，确保所有模型都遵守 A 股主架构边界。

---

## 1. 统一原则

所有模型接入都必须遵守：

- A 股 only
- `shared core layer = agently_adapter/a_share_core.py`
- `core flow = agently_adapter/agently_a_share_flow.py`
- `full compatibility workflow = agently_adapter/agently_daily_flow.py`
- `API service layer = hermass_platform/api/a_share_service.py`
- shell 脚本只是过渡入口
- 飞书是交付层，不是系统本体
- hermes-agent 是渠道、调度、技能运行时

---

## 2. 推荐加载顺序

### 轻量模型

只加载：

1. `config/prompts/local_model_architecture_prompt.md`

### 中等上下文模型

加载：

1. `config/prompts/runtime_architecture_prompt.md`
2. `config/prompts/local_model_architecture_prompt.md`

### 大上下文模型

加载：

1. `config/prompts/runtime_architecture_prompt.md`
2. `config/deepseek_context.md`
3. `docs/MODEL_ARCHITECTURE_USAGE_GUIDE.md`

---

## 3. 模型模板

- [deepseek_runtime.md](/Users/lv111101/Documents/hermass-observer-product/config/models/deepseek_runtime.md)
- [ollama_runtime.md](/Users/lv111101/Documents/hermass-observer-product/config/models/ollama_runtime.md)
- [lmstudio_runtime.md](/Users/lv111101/Documents/hermass-observer-product/config/models/lmstudio_runtime.md)
- [hermes_runtime.md](/Users/lv111101/Documents/hermass-observer-product/config/models/hermes_runtime.md)

---

## 4. 接入检查

新模型接入前，先用：

- [docs/HERMES_LOCAL_RUNTIME_ALIGNMENT_CHECKLIST.md](/Users/lv111101/Documents/hermass-observer-product/docs/HERMES_LOCAL_RUNTIME_ALIGNMENT_CHECKLIST.md)

新模型派工时，优先给：

- [docs/KIMI_TASK_EXTERNAL_RUNTIME_ALIGNMENT.md](/Users/lv111101/Documents/hermass-observer-product/docs/KIMI_TASK_EXTERNAL_RUNTIME_ALIGNMENT.md)

---

## 5. 一句话标准

> 任何模型都只能在 Hermass 主架构之上解释和组织信息，不能重定义架构本身。

