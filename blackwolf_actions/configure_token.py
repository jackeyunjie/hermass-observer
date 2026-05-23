#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / "config" / "secrets" / "blackwolf_token.txt"


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure local Blackwolf token without printing it.")
    parser.add_argument("--stdin", action="store_true", help="Read token from stdin.")
    args = parser.parse_args()

    token = sys.stdin.read().strip() if args.stdin else ""
    if not token:
        raise RuntimeError("empty token")

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    os.chmod(TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR)
    print({"status": "ok", "token_file": str(TOKEN_FILE), "mode": "0600", "token_written_to_logs": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
