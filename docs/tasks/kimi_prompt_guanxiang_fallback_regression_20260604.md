# KIMI 任务：观象“回答出了点问题”线上回归

在 `/Users/lv111101/Documents/hermass-observer-product` 和服务器 `/opt/hermass` 分别做观象链路回归。不要排查 public 静态文件、上传、AppleDouble 或 Nginx 静态目录问题，本任务只查 `/api/chat/query`。

## 背景

用户反馈：点击“观象”后提示“回答出了点问题，重试或直接看页面内容”。

本地已做代码修复：

- `web/main.py` 的 `/api/chat/query` 内部异常兜底从 HTTP 500 改为 HTTP 200
- 返回可读规则兜底，字段包含 `degraded=true`、`error_type`、`error`
- 新增测试：`tests/unit/test_chat_query_fallback.py`

疑似根因：

- “更自然的解释”默认勾选，前端会传 `use_llm=true`
- Agently 路由/场景 Agent 调用 DeepSeek 时可能失败
- 失败时部分路径以前会返回 500，前端 catch 后只显示一句“回答出了点问题”

## 本地验收

执行：

```bash
cd /Users/lv111101/Documents/hermass-observer-product
.venv/bin/python -m py_compile web/main.py
.venv/bin/python -m pytest tests/unit/test_chat_query_fallback.py tests/unit/test_conversation_manager.py -q
```

然后用 FastAPI TestClient 或本地服务验证这 4 个请求都返回 HTTP 200：

```bash
curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H 'Content-Type: application/json' \
  -d '{"message":"现在能不能做","page_context":"/","mode":"chat","use_llm":true}' | python -m json.tool

curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H 'Content-Type: application/json' \
  -d '{"message":"今天先看什么方向","page_context":"/","mode":"chat","use_llm":true}' | python -m json.tool

curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H 'Content-Type: application/json' \
  -d '{"message":"今日 601 只股票 ef≥2，全市场 10.9%——震荡选择环境。先看 电子、公用事业。","page_context":"/","mode":"chat","use_llm":true}' | python -m json.tool

curl -s -X POST http://127.0.0.1:8020/api/chat/query \
  -H 'Content-Type: application/json' \
  -d '{"message":"我应该先去哪一页","page_context":"/","mode":"chat","use_llm":false}' | python -m json.tool
```

验收标准：

- HTTP 状态码必须是 200
- JSON 必须包含 `answer`
- 如果触发降级，必须有 `degraded=true`
- 不允许用户侧再只看到“回答出了点问题”

## 线上部署后验收

服务器路径：`/opt/hermass`

部署后执行：

```bash
cd /opt/hermass
/opt/hermass/.venv/bin/python -m py_compile web/main.py
sudo systemctl restart hermass-console
sudo systemctl status hermass-console --no-pager
```

线上接口验收：

```bash
curl -s -X POST http://localhost:8020/api/chat/query \
  -H 'Content-Type: application/json' \
  -d '{"message":"现在能不能做","page_context":"/","mode":"chat","use_llm":true}' | python -m json.tool

curl -s -X POST http://localhost:8020/api/chat/query \
  -H 'Content-Type: application/json' \
  -d '{"message":"今日 601 只股票 ef≥2，全市场 10.9%——震荡选择环境。先看 电子、公用事业。","page_context":"/","mode":"chat","use_llm":true}' | python -m json.tool
```

浏览器验收：

1. 打开 `http://console.supertrader.world/`
2. 点击顶部“观象”，发送“现在能不能做”
3. 点击首页“问观象 →”
4. 勾选“更自然的解释”重复一次
5. 取消“更自然的解释”重复一次

验收标准：

- 抽屉能正常打开
- 页面不能出现“回答出了点问题，重试或直接看页面内容”
- 如果 DeepSeek/Agently 不可用，页面必须显示“已切回规则回答”或类似降级说明
- 服务器日志如有 `chat_query failed`，记录异常类型和触发输入

## 输出

把结果写入：

`docs/tasks/completed/kimi_guanxiang_fallback_regression_20260604.md`

必须包含：

- 本地测试结果
- 线上 curl 结果摘要
- 浏览器操作结果
- 是否仍有 500
- 是否仍出现旧提示文案
- 如果失败，贴出 `journalctl -u hermass-console -n 80 --no-pager` 中相关异常摘要
