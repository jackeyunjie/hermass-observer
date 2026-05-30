"""Hermass 最小用户身份识别层.

不引入第三方认证库，不透传密码，只从 Nginx Basic Auth 的 Authorization
header 中提取 username，并在本地 SQLite 中维护轻量 profile。

用途:
  - 区分「谁在看」（8 人内测）
  - 支持用户分层首页（方向型/研究型/执行型）
  - 为观象 AI 提供 user_id 绑定会话记忆
  - 为反馈追踪提供 identity

约束:
  - 不做注册/登录页
  - 不改 Nginx 配置
  - 匿名用户（header 缺失）→ 默认 "执行型"，不报错
"""

from __future__ import annotations

import base64
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Request

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "outputs" / "user_profiles.db"

# 用户类型枚举（与 PRD 一致）
USER_TYPES = ("方向型", "研究型", "执行型")
DEFAULT_USER_TYPE = "执行型"


def _conn() -> sqlite3.Connection:
    """获取 SQLite 连接，自动创建表。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            username TEXT PRIMARY KEY,
            display_name TEXT NOT NULL DEFAULT '',
            user_type TEXT NOT NULL DEFAULT '执行型',
            email TEXT DEFAULT '',
            focus_stocks TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    con.commit()
    return con


def init_profiles(username_list: list[str] | None = None) -> None:
    """初始化种子用户（INSERT OR IGNORE，不会覆盖已有数据）。

    Args:
        username_list: Nginx htpasswd 中存在的用户名列表。
                       推荐在应用启动时调用一次。
    """
    con = _conn()
    now = datetime.now(timezone.utc).isoformat()
    defaults: list[tuple[str, str, str, str, str, str]] = []

    # 内置管理员
    defaults.append(("admin", "管理员", DEFAULT_USER_TYPE, "", "", now))

    # 批量为 htpasswd 用户创建占位 profile
    for username in (username_list or []):
        if not username or username == "admin":
            continue
        defaults.append((username, username, DEFAULT_USER_TYPE, "", "", now))

    con.executemany(
        """
        INSERT OR IGNORE INTO user_profiles
        (username, display_name, user_type, email, focus_stocks, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        defaults,
    )
    con.commit()
    con.close()


def get_profile(username: str) -> dict[str, Any] | None:
    """按 username 查询 profile，不存在返回 None。"""
    con = _conn()
    row = con.execute(
        "SELECT * FROM user_profiles WHERE username = ?",
        (username,),
    ).fetchone()
    con.close()
    if row is None:
        return None
    return dict(row)


def list_profiles() -> list[dict[str, Any]]:
    """列出所有用户 profile。"""
    con = _conn()
    rows = con.execute("SELECT * FROM user_profiles ORDER BY created_at").fetchall()
    con.close()
    return [dict(r) for r in rows]


def upsert_profile(username: str, **kwargs: Any) -> dict[str, Any]:
    """创建或更新用户 profile。

    可更新字段: display_name, user_type, email, focus_stocks
    user_type 必须是 USER_TYPES 之一，否则会被修正为默认值。
    """
    con = _conn()
    now = datetime.now(timezone.utc).isoformat()

    # 先查是否存在
    existing = con.execute(
        "SELECT * FROM user_profiles WHERE username = ?", (username,)
    ).fetchone()

    if existing is None:
        # 创建
        user_type = kwargs.get("user_type", DEFAULT_USER_TYPE)
        if user_type not in USER_TYPES:
            user_type = DEFAULT_USER_TYPE
        record = {
            "username": username,
            "display_name": kwargs.get("display_name", username),
            "user_type": user_type,
            "email": kwargs.get("email", ""),
            "focus_stocks": kwargs.get("focus_stocks", ""),
            "created_at": now,
        }
        con.execute(
            """
            INSERT INTO user_profiles
            (username, display_name, user_type, email, focus_stocks, created_at)
            VALUES (:username, :display_name, :user_type, :email, :focus_stocks, :created_at)
            """,
            record,
        )
        con.commit()
        con.close()
        return record

    # 更新：只覆盖传入的字段
    allowed = ("display_name", "user_type", "email", "focus_stocks")
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if "user_type" in updates and updates["user_type"] not in USER_TYPES:
        updates["user_type"] = DEFAULT_USER_TYPE

    if updates:
        sets = ", ".join(f"{k} = :{k}" for k in updates)
        updates["username"] = username
        con.execute(f"UPDATE user_profiles SET {sets} WHERE username = :username", updates)
        con.commit()

    row = con.execute(
        "SELECT * FROM user_profiles WHERE username = ?", (username,)
    ).fetchone()
    con.close()
    return dict(row) if row else {}


def get_current_username(request: Request) -> str:
    """从 Nginx Basic Auth 的 Authorization header 中提取 username。

    解析失败或 header 缺失时返回 "anonymous"。
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return "anonymous"
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        username, _ = decoded.split(":", 1)
        return username.strip() or "anonymous"
    except Exception:
        return "anonymous"


def get_current_profile(request: Request) -> dict[str, Any]:
    """获取当前请求的 user profile。

    - 从 Basic Auth header 提取 username
    - 若该用户首次访问，自动创建默认 profile
    - 若 header 缺失，为 anonymous 创建 profile（user_type 默认执行型）
    """
    username = get_current_username(request)
    profile = get_profile(username)
    if profile is None:
        profile = upsert_profile(
            username,
            display_name=username,
            user_type=DEFAULT_USER_TYPE,
        )
    # 确保 user_type 合法
    if profile.get("user_type") not in USER_TYPES:
        profile = upsert_profile(username, user_type=DEFAULT_USER_TYPE)
    return profile
