---
name: clauver-telephony
description: >
  Make AI phone calls on your behalf. Clauver calls, speaks your message,
  listens for a reply, and brings it back — using your existing Hermes LLM
  at zero extra AI cost.
version: 1.0.0
author: Mustafa Ramax
license: AGPL-3.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [voice, telephony, phone, calling, outbound, accessibility, livekit, sip]
    homepage: https://github.com/mustafa-ramax/clauver-voice-hermes
    related_skills: [telephony]
---

# Clauver Telephony — AI Phone Calls for Hermes

Make real phone calls on your behalf. You type what you want to say — Clauver
calls, speaks for you, listens, and brings the reply back.

## When to Use This Skill

- User wants to make a phone call or deliver a voice message
- User wants to book an appointment by phone
- User wants to tell someone something but can't or doesn't want to call themselves
- User says "call", "phone", "ring", "tell them by phone", etc.

## How It Works

Use the `dispatch_clauver_call` MCP tool. The worker starts automatically
when a call is requested — no manual process management needed.

## Tool: dispatch_clauver_call

### Parameters

- `phone_number` (string, required) — E.164 format, e.g. `+61412345678`
- `task` (string, required) — The exact message or goal for the call
- `target_name` (string, optional) — Name of the person being called
- `boss` (string, optional) — Who the call is on behalf of (defaults to BOSS_NAME in .env)

### Examples

**"Tell my manager I'm sick today"**
```
dispatch_clauver_call(
  phone_number="+61412345678",
  task="Tell them I'm unwell today and won't be coming to work. Ask if they want to pass anything back."
)
```

**"Book a dentist appointment for tomorrow at 2pm"**
```
dispatch_clauver_call(
  phone_number="+61398765432",
  task="Book an appointment for tomorrow at 2pm. If unavailable, ask for the next available slot.",
  target_name="Reception"
)
```

**"Call my partner and say I'm running 20 minutes late"**
```
dispatch_clauver_call(
  phone_number="+61400111222",
  task="Say I'm running about 20 minutes late, sorry.",
  target_name="Sarah"
)
```

## Setup (One Time)

Run the installer (clones repo, installs deps, registers MCP server):

```bash
bash <(curl -sL https://raw.githubusercontent.com/mustafa-ramax/clauver-voice-hermes/main/setup.sh)
```

Or if you prefer not piping to bash:
```bash
git clone https://github.com/mustafa-ramax/clauver-voice-hermes.git ~/.clauver
cd ~/.clauver && bash setup.sh
```

Then fill in 4 values in `~/.clauver/.env`:

```
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your-key
LIVEKIT_API_SECRET=your-secret
SIP_OUTBOUND_TRUNK_ID=your-trunk-id
```

Get these from [cloud.livekit.io](https://cloud.livekit.io) (free tier available).
The SIP trunk connects to your phone provider (e.g. Twilio).

That's it. LLM, TTS, and STT are auto-detected from your Hermes config.

## What It Costs

- **AI (LLM/TTS/STT):** $0 extra — uses your existing Hermes provider
- **Phone minutes:** ~$0.013/min (Twilio SIP, or your provider's rate)
- **Phone number:** ~$1/month (Twilio, or similar)

## Troubleshooting

**Call not going through?**
- Check logs: `cat ~/.clauver/clauver-agent.log`
- Verify LiveKit keys in `~/.clauver/.env`
- Make sure ffmpeg is installed: `brew install ffmpeg` (macOS) / `apt install ffmpeg` (Linux)
- Make sure you have a good internet connection

**Worker not starting?**
- Check: `cat /tmp/clauver-worker.pid` — if empty, worker failed to start
- Check logs for errors: `tail -20 ~/.clauver/clauver-agent.log`

**Want the worker always running (faster calls)?**
- Add `CLAUVER_WORKER_MODE=persistent` to `~/.clauver/.env`
- Start manually: `cd ~/.clauver && .venv/bin/python agent.py dev`

## Safety

- Clauver always identifies itself as an AI assistant — never pretends to be you
- Always confirm before placing a call
- Never dial emergency numbers
- The task message is delivered exactly as you write it — no embellishment
