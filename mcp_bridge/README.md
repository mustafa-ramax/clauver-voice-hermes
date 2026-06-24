# Clauver MCP Bridge

Minimal Python MCP bridge for Clauver.

This bridge exposes one MCP tool that dispatches an outbound Clauver call through the LiveKit API.

## Tool

### `dispatch_clauver_call`

Dispatch a Clauver outbound call on behalf of the user.

#### Parameters

- `phone_number` (string, required)  
  Target phone number in strict E.164 format, for example: `+61412345678`

- `task` (string, required)  
  Exact message or concrete goal for the call

- `target_name` (string, optional)  
  Name of the person being called

- `boss` (string, optional)  
  Name of the user the assistant is speaking for, defaults to `boss`

#### Returns

A structured result including:

- `dispatch_id`
- `room`
- `agent_name`
- `request_id`
- `metadata`

## Project role

This MCP bridge is part of the main Clauver Python project.

It does not place calls itself. Its job is to:
1. validate tool inputs
2. build a safe dispatch request
3. create an explicit LiveKit agent dispatch
4. return structured dispatch details

The actual call handling remains in the LiveKit agent worker.

## Files

- `server.py` — MCP stdio server
- `tools/dispatch_call.py` — tool handler
- `lib/config.py` — config/env helpers
- `lib/validate.py` — input validation
- `../dispatch_api.py` — shared LiveKit dispatch helper

## Requirements

Install project dependencies from the repo root:

```bash
pip install -r requirements.txt
```

Make sure your environment contains:

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `BOSS_NAME`

Optional:

- `CLAUVER_AGENT_NAME` (defaults to `clauver-general`)

## Run locally

From the repo root:

```bash
python -m mcp_bridge.server
```

This starts the MCP server over stdio.

## Local testing

Before wiring Claude Desktop or another MCP client, first confirm that LiveKit dispatch works directly:

```bash
python test_dispatch_api.py
```

Then start the MCP server:

```bash
python -m mcp_bridge.server
```

## Notes

- This is intentionally a small v1.
- It uses the LiveKit API directly, not `lk` CLI.
- It exposes one tool only.
- It does not yet include webhook processing, transcript summaries, IVR/DTMF handling, or Docker-specific packaging.