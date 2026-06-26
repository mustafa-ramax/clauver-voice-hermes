# Clauver — Your AI Voice, For Real Phone Calls

Clauver is an AI voice assistant that makes **real phone calls** on your behalf.
You type what you want to say — Clauver calls, speaks, listens, and brings back the reply.

Built for [Hermes Agent](https://github.com/NousResearch/hermes-agent). Zero extra AI cost.

- **Free TTS** — Edge TTS (Microsoft neural voices, 41+ languages) Hermes deafult
- **Free STT** — Local Whisper (runs on your CPU) Hermes deafult
- **Free LLM** — Uses whatever you already pay for in Hermes
- **You only pay phone minutes** — ~$0.013/min via Twilio SIP

---

## What Clauver Can Do Today

- ✅ **Real two-way conversation** — not a one-way recorded message
- ✅ **Delivers your message** and waits for a reply
- ✅ **Handles voicemail** — detects it and leaves a short message
- ✅ **Transfers to a human** if the person asks to speak to someone
- ✅ **Logs call outcomes** — status, what was said, booking details
- ✅ **Auto-managed worker** — starts on demand, stops after 2 min idle
- ✅ **Auto-detects providers** — reads your Hermes LLM/TTS/STT config

---

## Examples

Just talk to Hermes naturally:

> **"Call my boss and tell them I'm sick today"**
> → Clauver calls, delivers the message, asks if they want to pass anything back, logs the reply.

> **"Book a dentist appointment for tomorrow at 2pm"**
> → Clauver calls, negotiates the time, confirms the slot, logs the booking.

> **"Call my partner and say I'm running 20 minutes late"**
> → Done in 30 seconds. Message delivered.

---

## Setup (3 Steps)

### 1. Install the skill

```bash
hermes skills install https://raw.githubusercontent.com/mustafa-ramax/clauver-voice-hermes/main/skill/SKILL.md
```

### 2. Run the setup script

```bash
bash <(curl -sL https://raw.githubusercontent.com/mustafa-ramax/clauver-voice-hermes/main/setup.sh)
```

Or clone manually (works in Git Bash on Windows):
```bash
git clone https://github.com/mustafa-ramax/clauver-voice-hermes.git ~/.clauver && cd ~/.clauver && bash setup.sh
```

This clones the repo to `~/.clauver/`, installs dependencies, and registers the MCP server in Hermes.

### 3. Add your LiveKit keys

Edit `~/.clauver/.env` and fill in 4 values:

```env
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your-key
LIVEKIT_API_SECRET=your-secret
SIP_OUTBOUND_TRUNK_ID=your-trunk-id
```

**Where to get these:**
- **LiveKit Cloud** — Free for builders (no credit card): [livekit.com/pricing](https://livekit.com/pricing)
- **SIP Trunk** — Twilio or any LiveKit-compatible SIP provider. Gives you a phone number.
- **ffmpeg** — Required for Edge TTS: `brew install ffmpeg` (macOS) / `apt install ffmpeg` (Linux)

Restart Hermes, then say: *"Call +61... and tell them ..."*

---

## What You Get for Free

| Component | Free Default | Premium Upgrade |
|-----------|-------------|-----------------|
| **TTS** | Edge TTS (Microsoft neural, $0) | `CLAUVER_TTS_OVERRIDE=cartesia` |
| **STT** | Local Whisper (CPU, $0) | `CLAUVER_STT_OVERRIDE=deepgram` |
| **LLM** | Your Hermes provider ($0 extra) | `CLAUVER_LLM_OVERRIDE=openai` |

All providers are auto-detected from `~/.hermes/config.yaml`. No extra configuration needed.

---

## Configuration

Edit `~/.clauver/.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `LIVEKIT_URL` | ✅ | Your LiveKit Cloud WebSocket URL |
| `LIVEKIT_API_KEY` | ✅ | LiveKit API key |
| `LIVEKIT_API_SECRET` | ✅ | LiveKit API secret |
| `SIP_OUTBOUND_TRUNK_ID` | ✅ | Your SIP trunk ID |
| `BOSS_NAME` | — | Your name (default: "Max") |
| `CLAUVER_TTS_OVERRIDE` | — | Force TTS: `cartesia`, `elevenlabs`, `openai`, `edge` |
| `CLAUVER_STT_OVERRIDE` | — | Force STT: `deepgram`, `openai`, `elevenlabs` |
| `CLAUVER_TTS_API_KEY` | — | API key for your TTS override |
| `CLAUVER_STT_API_KEY` | — | API key for your STT override |
| `CLAUVER_LLM_OVERRIDE` | — | Force LLM: `openai` |
| `CLAUVER_WORKER_MODE` | — | `auto` (default) or `persistent` (24/7) |

**Logs:** `~/.clauver/clauver-agent.log`

---

## How It Works

```
You → Hermes → MCP tool → Worker auto-starts → LiveKit → SIP → Phone rings
                                  ↓
                    LLM / TTS / STT from your Hermes config
                                  ↓
                    Call outcome logged to clauver-agent.log
```

1. You ask Hermes to make a call
2. Hermes calls the `dispatch_clauver_call` MCP tool
3. The worker starts automatically (if not already running)
4. LiveKit connects to your SIP trunk and dials the number
5. Clauver speaks, listens, handles the conversation
6. Result is logged — status, outcome, details

---

## Cost Comparison

| | Clauver | Bland.ai | Vapi |
|---|---|---|---|
| Phone minutes | ~$0.013/min | ~$0.09/min | $0.05–0.15/min |
| AI cost | $0 (reuse Hermes) | included in fee | included in fee |
| LiveKit account | Free tier | N/A | N/A |
| Real conversation | ✅ | ✅ | ✅ |
| Inbound calls | 🔜 roadmap | ❌ | ❌ |
| Self-hosted | ✅ | ❌ | ❌ |
| Open source | ✅ | ❌ | ❌ |
| Returns structured results | 🔜 roadmap | ❌ | partial |

---

## Supported Providers (Auto-Detected)

**LLM:** All 30+ Hermes providers — Bedrock, OpenRouter, OpenAI, DeepSeek, xAI, Anthropic, Gemini, Kimi, MiniMax, custom endpoints, Ollama, and more.

**TTS:** edge ✨free, openai, elevenlabs, cartesia, xai, gemini, mistral, deepgram

**STT:** local whisper ✨free, deepgram, openai, elevenlabs, mistral

Detected automatically from `~/.hermes/config.yaml`. Switch providers in Hermes → Clauver uses the new one on the next call.

---

## Roadmap

- 🔜 **Call results returned to Hermes chat** — see "Booked for 2pm" directly in conversation, not just logs
- 🔜 **Inbound calls** — Clauver answers your phone, triages, takes messages (LiveKit SIP supports this natively — needs agent code)
- 🔜 **Call recordings + transcripts** — saved and summarised after each call
- 🔜 **Custom agent modes** — booking, enquiry, message-delivery with different behaviors and tools

The architecture is ready for all of these. Contributions welcome.

---

## Troubleshooting

**Call not going through?**
Check your LiveKit keys in `~/.clauver/.env` and look at logs: `cat ~/.clauver/clauver-agent.log`

**Worker not starting?**
Remove stale PID file: `rm -f /tmp/clauver-worker.pid` — then try again.

**Voice sounds robotic?**
Upgrade TTS: add `CLAUVER_TTS_OVERRIDE=cartesia` + `CLAUVER_TTS_API_KEY=...` to `.env`

**Slow response after greeting?**
Local Whisper is CPU-bound. Add `CLAUVER_STT_OVERRIDE=deepgram` + `CLAUVER_STT_API_KEY=...` for streaming STT.

**Bedrock model error?**
Newer Claude models require a cross-region inference profile. The bridge handles this automatically — if you still see errors, set `CLAUVER_LLM_OVERRIDE=openai` as a workaround.

---

## Contributing

PRs are welcome — especially for roadmap items.

The hard infrastructure work is done (LiveKit integration, provider bridge, MCP, worker lifecycle). Adding features on top is straightforward.

**To develop:**
```bash
cd ~/.clauver  # or wherever you cloned
source .venv/bin/activate
python agent.py dev          # start worker manually
python test_dispatch_api.py  # test a call dispatch
```

**Areas that need help:**
- Structured result callback to MCP (so Hermes sees call outcomes in chat)
- Inbound call handler (LiveKit SIP already supports it — needs agent code)
- Call recording + transcript pipeline
- Docker one-command deployment

---

## License

**AGPL-3.0** — Free to use, modify, and self-host. If you deploy a modified version as a network service, you must open-source your changes.

Commercial licensing available — contact for details.

---

## Links

- [Clauver (Hermes edition)](https://github.com/mustafa-ramax/clauver-voice-hermes)
- [Clauver (original, any agent)](https://github.com/mustafa-ramax/clauver-voice)
- [Hermes Agent](https://github.com/NousResearch/hermes-agent)
- [LiveKit](https://livekit.io)
- [LiveKit Cloud (free tier)](https://livekit.com/pricing)
