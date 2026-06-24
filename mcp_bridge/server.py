"""
MCP stdio server for Clauver outbound call dispatch.
"""

from __future__ import annotations

import asyncio
import json
import logging

from pathlib import Path

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mcp_bridge.lib.config import ensure_livekit_env
from mcp_bridge.tools.dispatch_call import dispatch_clauver_call

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clauver-mcp-bridge")

server = Server("clauver-mcp-bridge")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="dispatch_clauver_call",
            description=(
                "Dispatch a Clauver outbound phone call on behalf of the user. "
                "Use this for message delivery calls with a specific phone number and task."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "Target phone number in strict E.164 format, e.g. +61412345678",
                    },
                    "task": {
                        "type": "string",
                        "description": "Exact message or concrete call goal to communicate",
                    },
                    "target_name": {
                        "type": "string",
                        "description": "Optional name of the person being called",
                    },
                    "boss": {
                        "type": "string",
                        "description": "Optional name of the user the assistant is speaking for; defaults to boss",
                    },
                },
                "required": ["phone_number", "task"],
                "additionalProperties": False,
            },
        )
    ]


@server.call_tool()
async def call_tool(
    name: str, arguments: dict[str, object] | None
) -> list[TextContent]:
    if name != "dispatch_clauver_call":
        raise ValueError(f"Unknown tool: {name}")

    args = arguments or {}

    result = await dispatch_clauver_call(
        phone_number=args.get("phone_number"),
        task=args.get("task"),
        target_name=args.get("target_name"),
        boss=args.get("boss", "boss"),
    )

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "status": "ok",
                    "dispatch_id": result["dispatch_id"],
                    "room": result["room"],
                    "agent_name": result["agent_name"],
                    "request_id": result["request_id"],
                    "metadata": result["metadata"],
                },
                ensure_ascii=False,
            ),
        )
    ]


async def serve() -> None:
    ensure_livekit_env()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        logger.info("Shutting down Clauver MCP bridge")
    except Exception as exc:
        logger.error("Failed to start Clauver MCP bridge: %s", exc)
        raise


if __name__ == "__main__":
    main()