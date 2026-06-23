# Clauver — Copilot Instructions

## What this project is

Clauver is an AI phone assistant that makes outbound calls on behalf of a user with a voice condition. It speaks transparently on behalf of the owner (the "boss") — never pretending to be them. Built with LiveKit Agents + SIP, Python only.

## Commands

```bash
# Install
pip install -r requirements.txt
python agent.py download-files     # downloads Silero VAD model files

# Run agent worker
python agent.py dev                # connects to LiveKit and waits for dispatches

# Run MCP bridge (stdio server)
python mcp_bridge/server.py

# Test a real dispatch (end-to-end)
python test_dispatch_api.py
```

Test dispatch env overrides:
```
CLAUVER_TEST_PHONE_NUMBER=+61412345678
CLAUVER_TEST_BOSS=Max
CLAUVER_TEST_TARGET_NAME=Steve
CLAUVER_TEST_TASK="Tell Steve that Max won't be in today."
```

Required env vars (see `.env.example`):
```
LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
DEEPGRAM_API_KEY, CARTESIA_API_KEY, OPENAI_API_KEY
SIP_OUTBOUND_TRUNK_ID
BOSS_NAME=Max          # default boss name for calls
CLAUVER_AGENT_NAME=clauver-general  # must match WorkerOptions agent_name in agent.py
```

## Architecture

### Call dispatch flow

```
Claude (via MCP) → mcp_bridge/server.py (stdio MCP server)
  → mcp_bridge/tools/dispatch_call.py  (validates, then calls dispatch_api)
    → dispatch_api.create_dispatch()   (shared LiveKit dispatch helper)
      → LiveKit API → agent worker (agent.py) picks up the job
        → creates SIP participant → dials phone number → conducts call
```

`dispatch_api.py` is the **shared internal dispatch path** — used by both the MCP bridge and direct scripts. Do not bypass it in favour of raw LiveKit calls.

### Agent files

- `agent.py` — primary agent, handles all real call types (message delivery, bookings, etc.)
- `agent-local.py` — local dev variant
- `agent-cloud.py` — cloud-optimised variant

The `OutboundCaller` class in `agent.py` holds call state (`call_result`) and exposes four `@function_tool` methods the LLM can call:

| Tool | Purpose |
|---|---|
| `save_result` | Record call outcome (call before ending) |
| `end_call` | Hang up — only after spoken goodbye |
| `handle_voicemail` | Leave voicemail then hang up |
| `transfer_call` | SIP transfer to a human |

### MCP bridge layout

```
mcp_bridge/
  server.py          # MCP stdio server, exposes dispatch_clauver_call tool
  tools/
    dispatch_call.py # validates + calls dispatch_api.create_dispatch()
  lib/
    validate.py      # strict input validation
    config.py        # env-based config helpers
    metadata.py      # metadata construction
```

### Dispatch metadata schema (v1)

```json
{
  "version": "1",
  "mode": "message_delivery",
  "source": "dispatch_api",
  "request_id": "<uuid>",
  "created_at": "<ISO 8601 UTC>",
  "phone_number": "+61412345678",
  "boss": "Max",
  "target_name": "Steve",
  "task": "Tell Steve that Max is sick and won't be in today."
}
```

Do not add free-form prompt fields to metadata. Keep the schema stable.

## Key conventions

### Validation is strict by design
- Phone numbers must be strict E.164 (e.g. `+61412345678`). Validated via regex in `validate.py`.
- Tasks are rejected if vague or too short (`< 8 chars`). The `VAGUE_TASKS` set in `validate.py` is the authoritative list.
- All validation happens in `mcp_bridge/lib/validate.py` before dispatch — fail fast.

### Agent identity
- The agent always identifies as Clauver, calling on behalf of the boss.
- Never pretend to be the boss. Never invent task details. The `task` field is ground truth.

### Logging over print
Use `logging` for all output. `print()` is reserved for `test_dispatch_api.py` only.

### Agent name must match
The `agent_name` in `WorkerOptions` (`agent.py`) must match the name used in `CreateAgentDispatchRequest`. Default is `clauver-general`, overridable via `CLAUVER_AGENT_NAME`.

### VAD is prewarmed
`prewarm()` loads Silero VAD before jobs arrive — `proc.userdata["vad"]` is always available in `entrypoint`.

### Tool call ordering in agent
The LLM instructions enforce strict tool ordering: `save_result` → spoken goodbye → `end_call`. Do not reorder these in prompts or tool implementations.
