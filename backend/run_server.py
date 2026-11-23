"""Windows 兼容的后端启动入口。

psycopg 3 的异步模式不支持 Windows 默认的 ProactorEventLoop，
因此显式使用 SelectorEventLoop。请通过本文件启动后端：

    python run_server.py
"""
from __future__ import annotations

import argparse
import asyncio

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 AI 智播课堂后端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        loop=asyncio.SelectorEventLoop,
    )


if __name__ == "__main__":
    main()
