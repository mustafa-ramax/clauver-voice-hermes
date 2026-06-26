"""
MCP tool logic for dispatching Clauver outbound calls.
"""

from __future__ import annotations

from typing import Any

from dispatch_api import create_dispatch
from mcp_bridge.lib.config import get_agent_name
from mcp_bridge.lib.worker_manager import ensure_worker_running
from mcp_bridge.lib.validate import (
    validate_boss,
    validate_phone_number,
    validate_target_name,
    validate_task,
)


async def dispatch_clauver_call(
    phone_number: str,
    task: str,
    target_name: str | None = None,
    boss: str | None = None,
) -> dict[str, Any]:
    """
    Validate inputs, ensure worker is running, and create a LiveKit dispatch.
    """
    validated_phone_number = validate_phone_number(phone_number)
    validated_task = validate_task(task)
    validated_target_name = validate_target_name(target_name)
    import os
    resolved_boss = boss or os.environ.get("BOSS_NAME") or "boss"
    validated_boss = validate_boss(resolved_boss)

    # Ensure agent worker is alive before dispatching
    worker_status = await ensure_worker_running()

    result = await create_dispatch(
        phone_number=validated_phone_number,
        task=validated_task,
        target_name=validated_target_name,
        boss=validated_boss,
        agent_name=get_agent_name(),
    )
    result["worker_status"] = worker_status
    return result