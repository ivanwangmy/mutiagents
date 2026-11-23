from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.tools.base import ToolDefinition, ToolResult

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Asia/Shanghai")
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"未知时区：{name}") from exc


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"时间格式无效：{value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


async def datetime_tool(arguments: dict[str, Any]) -> Any:
    action = arguments.get("action", "now")
    if action == "now":
        zone = _tz(arguments.get("timezone"))
        now = datetime.now(zone)
        return {
            "timezone": str(zone),
            "iso": now.isoformat(timespec="seconds"),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "weekday": WEEKDAYS[now.weekday()],
            "timestamp": int(now.timestamp()),
        }
    if action == "diff":
        start = _parse_iso(str(arguments.get("start", "")))
        end = _parse_iso(str(arguments.get("end", "")))
        delta: timedelta = end - start
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": delta.days,
            "hours": round(delta.total_seconds() / 3600, 2),
            "seconds": int(delta.total_seconds()),
            "direction": "after" if delta.total_seconds() >= 0 else "before",
        }
    if action == "convert":
        value = _parse_iso(str(arguments.get("value", "")))
        zone = _tz(arguments.get("timezone"))
        converted = value.astimezone(zone)
        return {
            "source": value.isoformat(),
            "timezone": str(zone),
            "iso": converted.isoformat(timespec="seconds"),
            "weekday": WEEKDAYS[converted.weekday()],
        }
    raise ValueError("action 必须是 now / diff / convert 之一")


def build_tool() -> ToolDefinition:
    return ToolDefinition(
        name="datetime",
        description="查询当前日期时间、计算两个时间点的间隔，或把时间转换到指定时区。",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["now", "diff", "convert"],
                    "description": "now=当前时间；diff=时间差；convert=时区转换",
                },
                "timezone": {"type": "string", "description": "IANA 时区，如 Asia/Shanghai"},
                "start": {"type": "string", "description": "diff 的起始时间（ISO 8601）"},
                "end": {"type": "string", "description": "diff 的结束时间（ISO 8601）"},
                "value": {"type": "string", "description": "convert 的原始时间（ISO 8601）"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        handler=datetime_tool,
        timeout_seconds=3.0,
    )


def error_result(message: str) -> ToolResult:
    return ToolResult(ok=False, error=message)
