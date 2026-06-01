# Smoke Tests（冒烟测试）

本目录存放**端到端冒烟测试**，覆盖 HTTP 层、LLM 链路、关键用户交互路径。

> 与 `tests/unit/` 的区别：
> - **unit**：隔离环境，不依赖外部服务，运行快。
> - **smoke**：需要真实服务或真实 API key，验证"端到端能跑通"。

---

## 运行方式

```bash
# 运行全部冒烟测试
bash scripts/run_tests.sh smoke

# 或直接用 pytest
source .venv/bin/activate
pytest tests/smoke/ -q
```

---

## 环境变量

| 变量名 | 作用 | 必填场景 |
|--------|------|----------|
| `HERMASS_DEEPSEEK_API_KEY` | 调用真实 DeepSeek API（value 分析、chat 增强链路） | 运行 `test_e2e_chat_value_llm.py`、`test_http_chat_value_llm.py`、`test_e2e_llm.py` 等 |

### 设置示例

```bash
export HERMASS_DEEPSEEK_API_KEY="sk-..."
```

若未设置，相关用例会**跳过**（`pytest.skip`），不会导致测试失败。

---

## 用例清单

| 文件 | 覆盖范围 | 需要真实 API |
|------|----------|-------------|
| `test_http_chat_value_llm.py` | `/api/chat/query` → value 分支 | ✅ DeepSeek |
| `test_e2e_chat_value_llm.py` | `_llm_chat_answer()` value 分支 | ✅ DeepSeek |
| `test_e2e_llm.py` | `_llm_chat_answer()` 全链路 | ✅ DeepSeek |
| `test_e2e_value_llm.py` | 价值分析独立链路 | ✅ DeepSeek |
| `test_agently_chains.py` | Agently 场景链编排 | ❌ |

---

## 新增用例约定

1. 文件名前缀：`test_`
2. 需要真实 API 的用例，在函数开头检查环境变量并 `pytest.skip`
3. 每个用例至少验证：HTTP 200、关键字段存在、provider 符合预期
4. 禁止修改业务代码来适配测试
