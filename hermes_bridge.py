"""
Hermes Config Bridge for Clauver.

Reads ~/.hermes/config.yaml and returns ready-to-use LiveKit plugin instances
for STT, TTS, and LLM — so Clauver uses whatever the user already has configured
in Hermes, with zero extra API keys or costs.
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from livekit.agents import stt, tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions, NOT_GIVEN

logger = logging.getLogger("hermes-bridge")

_config_cache: dict | None = None


def load_hermes_config() -> dict:
    """Load and cache ~/.hermes/config.yaml."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    config_path = Path.home() / ".hermes" / "config.yaml"
    if not config_path.exists():
        _config_cache = {}
        return _config_cache
    with open(config_path) as f:
        _config_cache = yaml.safe_load(f) or {}
    return _config_cache


def _require_env(name: str, provider: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Hermes is configured to use {provider} but {name} is not set"
        )
    return value


def _strip_global_prefix(model_id: str) -> str:
    """Strip 'global.' prefix if present: global.anthropic.claude-... → anthropic.claude-..."""
    if model_id.startswith("global."):
        return model_id[len("global."):]
    return model_id


# =============================================================================
# LLM
# =============================================================================


def build_llm():
    """Return a LiveKit LLM plugin instance based on Hermes config."""
    # Allow override via env var — useful when Hermes provider (e.g. bedrock)
    # doesn't support the model ID format expected by the LiveKit plugin.
    override = os.getenv("CLAUVER_LLM_OVERRIDE", "").strip().lower()
    if override == "openai":
        from livekit.plugins import openai as openai_plugin
        api_key = _require_env("OPENAI_API_KEY", "OpenAI")
        logger.info("CLAUVER_LLM_OVERRIDE=openai — using OpenAI LLM (gpt-5.3-chat-latest)")
        return openai_plugin.LLM(model="gpt-5.3-chat-latest", api_key=api_key)

    config = load_hermes_config()
    model_config = config.get("model", {})
    provider = model_config.get("provider", "openai")
    model_id = model_config.get("default", "gpt-5.3-chat-latest")

    if provider == "bedrock":
        from livekit.plugins import aws

        region = config.get("bedrock", {}).get("region", "us-east-1")
        bedrock_model = _strip_global_prefix(model_id)
        return aws.LLM(model=bedrock_model, region=region)

    elif provider == "openrouter":
        from livekit.plugins import openai

        api_key = _require_env("OPENROUTER_API_KEY", "OpenRouter")
        return openai.LLM(
            model=model_id,
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )

    elif provider == "anthropic":
        from livekit.plugins import anthropic

        api_key = _require_env("ANTHROPIC_API_KEY", "Anthropic")
        return anthropic.LLM(model=model_id, api_key=api_key)

    elif provider == "openai":
        from livekit.plugins import openai

        return openai.LLM(model=model_id)

    else:
        from livekit.plugins import openai

        logger.warning(f"Unknown LLM provider '{provider}', falling back to openai/gpt-5.3-chat-latest")
        return openai.LLM(model="gpt-5.3-chat-latest")


# =============================================================================
# TTS
# =============================================================================


class _EdgeChunkedStream(tts.ChunkedStream):
    """ChunkedStream that generates audio via edge-tts and emits PCM16."""

    def __init__(self, *, tts_instance: "EdgeTTSAdapter", input_text: str, conn_options: APIConnectOptions):
        super().__init__(tts=tts_instance, input_text=input_text, conn_options=conn_options)
        self._voice = tts_instance._voice

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        import uuid
        import edge_tts
        from pydub import AudioSegment

        communicate = edge_tts.Communicate(self._input_text, self._voice)

        # Collect ALL MP3 bytes first — edge-tts streams partial MP3 fragments
        # that ffmpeg cannot decode individually (no complete frame headers).
        # Must buffer the full response before decoding.
        mp3_bytes = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_bytes += chunk["data"]

        if not mp3_bytes:
            return

        # Decode full MP3 → PCM16 24kHz mono in one shot
        audio = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
        audio = audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
        pcm_data = audio.raw_data

        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=24000,
            num_channels=1,
            mime_type="audio/pcm",
        )
        output_emitter.push(pcm_data)
        output_emitter.flush()


class EdgeTTSAdapter(tts.TTS):
    """Minimal Edge TTS adapter for LiveKit. ChunkedStream (batch) only."""

    def __init__(self, *, voice: str = "en-US-AvaMultilingualNeural"):
        from pydub.utils import which

        if which("ffmpeg") is None:
            raise RuntimeError(
                "EdgeTTSAdapter requires ffmpeg to be installed: brew install ffmpeg"
            )

        # NOTE: Using 24kHz output — LiveKit resamples to SIP rate (8-16kHz).
        # Test on real calls to confirm quality. If issues, try 16kHz.
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False, aligned_transcript=False),
            sample_rate=24000,
            num_channels=1,
        )
        self._voice = voice

    def synthesize(self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> tts.ChunkedStream:
        return _EdgeChunkedStream(tts_instance=self, input_text=text, conn_options=conn_options)


def build_tts():
    """Return a LiveKit TTS plugin instance based on Hermes config."""
    config = load_hermes_config()
    tts_config = config.get("tts", {})
    provider = tts_config.get("provider", "openai")

    if provider == "edge":
        voice = tts_config.get("edge", {}).get("voice", "en-US-AvaMultilingualNeural")
        return EdgeTTSAdapter(voice=voice)

    elif provider == "openai":
        from livekit.plugins import openai

        oai_cfg = tts_config.get("openai", {})
        return openai.TTS(
            model=oai_cfg.get("model", "gpt-4o-mini-tts"),
            voice=oai_cfg.get("voice", "alloy"),
        )

    elif provider == "elevenlabs":
        from livekit.plugins import elevenlabs

        el_cfg = tts_config.get("elevenlabs", {})
        _require_env("ELEVEN_API_KEY", "ElevenLabs TTS")
        return elevenlabs.TTS(
            voice_id=el_cfg.get("voice_id", "pNInz6obpgDQGcFmaJgB"),
            model=el_cfg.get("model_id", "eleven_multilingual_v2"),
        )

    elif provider == "cartesia":
        from livekit.plugins import cartesia

        _require_env("CARTESIA_API_KEY", "Cartesia TTS")
        return cartesia.TTS()

    else:
        from livekit.plugins import openai

        logger.warning(f"Unknown TTS provider '{provider}', falling back to openai/alloy")
        return openai.TTS(voice="alloy")


def is_streaming_tts() -> bool:
    """Return False for non-streaming TTS providers (edge), True otherwise."""
    config = load_hermes_config()
    provider = config.get("tts", {}).get("provider", "openai")
    return provider != "edge"


# =============================================================================
# STT
# =============================================================================


class WhisperSTTAdapter(stt.STT):
    """Minimal local Whisper STT adapter using faster-whisper. Batch mode only.

    Use with LiveKit's stt.StreamAdapter + Silero VAD for streaming on live calls.
    """

    def __init__(self, *, model: str = "base"):
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=False,
                interim_results=False,
                diarization=False,
                aligned_transcript=False,
                offline_recognize=True,
            )
        )
        self._model_size = model
        self._model = None  # lazy load

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
        return self._model

    async def _recognize_impl(
        self, buffer, *, language=None, conn_options=DEFAULT_API_CONNECT_OPTIONS
    ) -> stt.SpeechEvent:
        import asyncio
        import numpy as np
        from livekit.rtc import AudioFrame

        # Convert AudioBuffer (list[AudioFrame] | AudioFrame) to numpy array
        if isinstance(buffer, list):
            frames = buffer
        else:
            frames = [buffer]

        # Combine all frames into a single PCM array
        pcm_data = b""
        sample_rate = 16000
        for frame in frames:
            pcm_data += frame.data.tobytes() if hasattr(frame.data, 'tobytes') else bytes(frame.data)
            sample_rate = frame.sample_rate

        # Convert to float32 normalized [-1, 1]
        samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0

        # Resample to 16kHz if needed (whisper expects 16kHz)
        # Uses numpy linear interpolation — no scipy dependency needed.
        if sample_rate != 16000:
            num_samples = int(len(samples) * 16000 / sample_rate)
            samples = np.interp(
                np.linspace(0, len(samples) - 1, num_samples),
                np.arange(len(samples)),
                samples,
            ).astype(np.float32)

        # Run transcription in thread pool (CPU-bound)
        model = self._get_model()
        loop = asyncio.get_event_loop()
        segments, _ = await loop.run_in_executor(
            None, lambda: model.transcribe(samples, language=language if language and language is not NOT_GIVEN else None)
        )
        segments_list = await loop.run_in_executor(None, lambda: list(segments))

        text = " ".join(seg.text.strip() for seg in segments_list)

        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[
                stt.SpeechData(language=language if language and language is not NOT_GIVEN else "en", text=text, confidence=1.0)
            ],
        )


def build_stt():
    """Return a LiveKit STT plugin instance based on Hermes config."""
    # Check override first
    override = os.getenv("CLAUVER_STT_OVERRIDE", "").strip().lower()
    if override:
        if override == "deepgram":
            from livekit.plugins import deepgram

            return deepgram.STT()
        elif override == "openai":
            from livekit.plugins import openai

            return openai.STT()
        else:
            logger.warning(f"Unknown CLAUVER_STT_OVERRIDE '{override}', ignoring")

    config = load_hermes_config()
    stt_config = config.get("stt", {})
    provider = stt_config.get("provider", "openai")

    if provider == "local":
        model = stt_config.get("local", {}).get("model", "base")
        logger.warning(
            "Local Whisper STT is configured — audio will be processed in chunks on CPU. "
            "For better call quality set CLAUVER_STT_OVERRIDE=deepgram"
        )
        return WhisperSTTAdapter(model=model)

    elif provider == "openai":
        from livekit.plugins import openai

        oai_cfg = stt_config.get("openai", {})
        return openai.STT(model=oai_cfg.get("model", "whisper-1"))

    elif provider == "deepgram":
        from livekit.plugins import deepgram

        return deepgram.STT()

    elif provider == "elevenlabs":
        from livekit.plugins import elevenlabs

        _require_env("ELEVEN_API_KEY", "ElevenLabs STT")
        return elevenlabs.STT()

    else:
        from livekit.plugins import openai

        logger.warning(f"Unknown STT provider '{provider}', falling back to openai")
        return openai.STT()
