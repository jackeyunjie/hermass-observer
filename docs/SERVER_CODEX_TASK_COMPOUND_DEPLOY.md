# 服务器 Codex 任务 — 支线 A 复合场景部署

版本：v1.0  
日期：2026-05-31  
执行对象：服务器上的 Codex  
前置条件：Claude 审阅通过 + 本机 Trae 已 push 支线 A 代码  
目标：git pull 最新代码 → 编译 → 重启 → 冒烟验证复合场景

---

## 0. 背景

支线 A 为观象 AI 助手新增「复合场景」能力：watch_command + industry_scan 同时执行并合并结果。

改动的文件：
- `agently_adapter/qa_entry.py` — 新增 `_execute_compound()` 复合编排
- `agently_adapter/scenarios/watch_command.py` — 支持子链执行模式

具体 diff 由本机 Trae 完成并 push 到 `main` 分支。

---

## 1. 服务器信息

| 项 | 值 |
|------|------|
| IP | 8.130.125.201 |
| 项目路径 | `/opt/hermass` |
| 服务 | hermass-console (systemd, 8020) |
| Python | .venv 虚拟环境 |
| 网址 | http://console.supertrader.world |

---

## 2. 部署步骤

### Step 1 — git pull

```bash
cd /opt/hermass
git pull
```

### Step 2 — 语法验证

```bash
source .venv/bin/activate
python -m py_compile agently_adapter/qa_entry.py
python -m py_compile agently_adapter/scenarios/watch_command.py
```

### Step 3 — 重启服务

```bash
sudo systemctl restart hermass-console
sudo systemctl status hermass-console
```

确认 `active (running)`。

### Step 4 — 冒烟测试

```bash
# 首页可访问
curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/

# 已有功能不受影响（LLM 开关开）
curl -s -X POST http://localhost:8020/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"message":"现在能不能做","use_llm":true}' | python3 -m json.tool | grep provider

# 已有功能不受影响（LLM 开关关）
curl -s -X POST http://localhost:8020/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"message":"现在能不能做","use_llm":false}' | python3 -m json.tool | grep provider
```

### Step 5 — 兜底检查

```bash
# 确认无语法错误 traceback
sudo journalctl -u hermass-console -n 30 --no-pager | grep -i -E "error|traceback|exception" || echo "无异常日志"
```

---

## 3. 验收标准

- ✅ `sudo systemctl status hermass-console` → `active (running)`
- ✅ 首页 HTTP 200
- ✅ `use_llm=false` → `provider: rule_based`
- ✅ `use_llm=true` → `provider: agently_deepseek`
- ✅ 日志无 traceback

---

## 4. 回滚

```bash
cd /opt/hermass
git stash
sudo systemctl restart hermass-console
```

---

## 5. 完成后

在终端输出「支线 A 部署完成 ✅」+ 服务状态 + 冒烟结果汇总。
