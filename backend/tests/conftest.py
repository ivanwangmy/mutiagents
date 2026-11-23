from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    # psycopg 3 异步模式不支持 ProactorEventLoop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
