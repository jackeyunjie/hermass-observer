from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOKEN_SERVICE = "hermass.blackwolf"
TOKEN_ACCOUNT = "BLACKWOLF_TOKEN"


def read_token(allow_stdin: bool = False) -> str:
    env_token = os.environ.get("BLACKWOLF_TOKEN", "").strip()
    if env_token:
        return env_token

    keychain_token = read_keychain_token()
    if keychain_token:
        return keychain_token

    token_file = ROOT / "config" / "secrets" / "blackwolf_token.txt"
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return token

    if allow_stdin:
        token = sys.stdin.read().strip()
        if token:
            return token
    raise RuntimeError(
        "missing Blackwolf token. Run `python3 blackwolf_actions/configure_token.py --stdin` "
        "or set BLACKWOLF_TOKEN in the environment."
    )


def read_keychain_token() -> str:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", TOKEN_ACCOUNT, "-s", TOKEN_SERVICE, "-w"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def write_keychain_token(token: str) -> None:
    delete_cmd = ["security", "delete-generic-password", "-a", TOKEN_ACCOUNT, "-s", TOKEN_SERVICE]
    subprocess.run(delete_cmd, check=False, capture_output=True, text=True)
    subprocess.run(
        [
            "security",
            "add-generic-password",
            "-a",
            TOKEN_ACCOUNT,
            "-s",
            TOKEN_SERVICE,
            "-w",
            token,
            "-U",
        ],
        check=True,
    )
