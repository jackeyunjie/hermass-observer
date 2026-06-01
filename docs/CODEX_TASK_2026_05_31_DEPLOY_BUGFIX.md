# Codex Task — 2026-05-31 观象 Bug 修复部署

版本：v2.0（含 Claude 审阅建议）  
日期：2026-05-31  
执行对象：Codex  
前置条件：Claude 审阅已通过 ✅  
目标：将修改文件部署到生产服务器，重启服务，验证部署

---

## 0. 背景

观象 AI 助手前端测试 7/9 通过，2 项失败（Test 3 / Test 7）。已完成修复，Claude 审阅通过。

修复内容：
- **Test 3**：LLM 开关关时尊重用户选择，`_should_use_managed_llm` 改名为 `_user_wants_llm`（语义更准确）
- **Test 7**：代词（"它"/"这个"）→ 股票代码解析 + 对话历史注入 fusion + 行业数据预取
- **审阅后改进**：`_llm_chat_answer()` 加注释块分区，便于后续拆分

改动文件：

```
agently_adapter/agents/fusion.py            (+14)
agently_adapter/qa_entry.py                 (+19/-8)
agently_adapter/scenarios/industry_scan.py  (+1)
agently_adapter/scenarios/learn_topic.py    (+1)
agently_adapter/scenarios/market_overview.py(+1)
agently_adapter/scenarios/stock_checkup.py  (+1)
agently_adapter/scenarios/strategy_fit.py   (+1)
web/main.py                                 (+63/-12)
───────────────────────────────────────────────
8 files changed, +91 -18
```

---

## 1. 服务器信息

| 项 | 值 |
|------|------|
| IP | 8.130.125.201 |
| 项目路径 | `/opt/hermass` |
| 服务名 | `hermass-console`（systemd） |
| 端口 | 8020 |
| Python | `.venv` 虚拟环境 |
| Web URL | `http://console.supertrader.world` |
| 测试账号 | `hermass-test / Hermass2026!Lab` |

---

## 2. 部署步骤

### Step 1 — SSH 到服务器

```bash
ssh root@8.130.125.201
cd /opt/hermass
```

### Step 2 — 同步代码

**方式 A（推荐）：在服务器上 git pull**

如果你已从本机 push 到 remote：

```bash
cd /opt/hermass
git pull
```

**方式 B：从本机 rsync**

如果还没 push，从本机执行：

```bash
rsync -avz web/main.py root@8.130.125.201:/opt/hermass/web/
rsync -avz agently_adapter/ root@8.130.125.201:/opt/hermass/agently_adapter/
```

### Step 3 — 语法验证（部署前必须）

在服务器上执行：

```bash
cd /opt/hermass
source .venv/bin/activate
python -m py_compile web/main.py
python -m py_compile agently_adapter/qa_entry.py
python -m py_compile agently_adapter/agents/fusion.py
```

三项均应静默通过（无输出 = OK）。

### Step 4 — 重启服务

```bash
sudo systemctl restart hermass-console
sudo systemctl status hermass-console
```

确认状态为 `active (running)`，且 RestartSec 正常，不是 crash loop。

### Step 5 — 冒烟测试

```bash
# 首页可访问
curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/

# Test 3 验证：关闭 LLM → 应返回 rule_based
curl -s -X POST http://localhost:8020/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"message":"现在能不能做","use_llm":false}' | python3 -m json.tool

# Test 3 验证：打开 LLM → 应返回 agently_deepseek
curl -s -X POST http://localhost:8020/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"message":"现在能不能做","use_llm":true}' | python3 -m json.tool
```

验收标准：
- `use_llm=false` → `provider` = `"rule_based"`，`enhancement_used` = `false`
- `use_llm=true` → `provider` = `"agently_deepseek"`，`enhancement_used` = `true`

### Step 6 — 查看日志

```bash
sudo journalctl -u hermass-console -n 50 --no-pager
```

检查是否有 Python traceback 或异常（不应出现 NameError/ImportError/SyntaxError）。

---

## 3. 回滚方案

如果部署后出现问题：

```bash
cd /opt/hermass
git stash
sudo systemctl restart hermass-console
```

---

## 4. 安全规则

- **不要**修改 `.venv`、systemd unit 文件、nginx 配置
- **不要**碰 `outputs/conversations.db` 或 `outputs/trades.db`
- **不要**改 `DEEPSEEK_API_KEY` 环境变量
- 如果 rsync/scp 遇到权限问题，先 `chown` 再操作
- 部署前必须先在服务器上 `python -m py_compile` 验证语法

---

## 5. 完成后

1. 确认 `sudo systemctl status hermass-console` 为 `active (running)`
2. 确认三个冒烟测试都返回 HTTP 200
3. 在终端输出「部署完成 ✅」+ 服务状态摘要
