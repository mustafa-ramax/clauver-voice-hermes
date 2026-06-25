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
from dotenv import load_dotenv
from livekit.agents import stt, tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions, NOT_GIVEN

# Load Hermes .env for shared API keys (OPENROUTER_API_KEY, DEEPSEEK_API_KEY, etc.)
# Clauver's own .env (LiveKit keys) is loaded separately by agent.py.
# override=False ensures Clauver's own .env takes priority if both define the same key.
_hermes_env = Path.home() / ".hermes" / ".env"
if _hermes_env.exists():
    load_dotenv(_hermes_env, override=False)

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


def _bedrock_resolve_profile(model_id: str, region: str) -> str:
    """Resolve a bare Bedrock model ID to its cross-region inference profile.

    Newer Claude models require a 'us.' / 'eu.' / 'apac.' prefix.
    If the model already has a region prefix (including 'global.'), return as-is.
    """
    if model_id.startswith(("global.", "us.", "eu.", "apac.")):
        return model_id

    # Determine region prefix from AWS region
    if region.startswith("us-"):
        prefix = "us"
    elif region.startswith("eu-"):
        prefix = "eu"
    elif region.startswith("ap-"):
        prefix = "apac"
    else:
        prefix = "us"

    profiled = f"{prefix}.{model_id}"
    logger.info(f"Bedrock: using inference profile '{profiled}' (from '{model_id}')")
    return profiled


# =============================================================================
# LLM
# =============================================================================


def build_llm():
    """Return a LiveKit LLM plugin instance based on Hermes config.

    Supports all Hermes providers dynamically:
    - bedrock → aws.LLM (dedicated plugin, needs region)
    - anthropic → anthropic.LLM (dedicated plugin, native API)
    - All others → openai.LLM (OpenAI-compatible, uses base_url + api_key)
    """
    # Allow override via env var — useful when Hermes provider doesn't work
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
    base_url = model_config.get("base_url") or None  # treat "" as None

    # --- Special cases (need dedicated LiveKit plugins) ---

    if provider == "bedrock":
        from livekit.plugins import aws
        region = config.get("bedrock", {}).get("region", "us-east-1")
        # 'global.' is a valid cross-region inference profile prefix (routes to nearest region).
        # Bare model IDs (no prefix) get a region prefix added automatically.
        bedrock_model = _bedrock_resolve_profile(model_id, region)
        logger.info(f"Bedrock LLM: model={bedrock_model}, region={region}")
        return aws.LLM(model=bedrock_model, region=region)

    if provider == "anthropic":
        from livekit.plugins import anthropic
        api_key = _require_env("ANTHROPIC_API_KEY", "Anthropic")
        return anthropic.LLM(model=model_id, api_key=api_key)

    # --- Generic path: all OpenAI-compatible providers ---
    from livekit.plugins import openai

    # Resolve API key from known provider→env_var mapping
    api_key = _resolve_provider_key(provider, model_config)

    if base_url:
        logger.info(f"LLM provider '{provider}' via base_url={base_url}, model={model_id}")
        return openai.LLM(model=model_id, base_url=base_url, api_key=api_key)

    # No base_url in config — use defaults for known providers
    known_urls = {
        "openrouter": "https://openrouter.ai/api/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "xai": "https://api.x.ai/v1",
        "nvidia": "https://integrate.api.nvidia.com/v1",
        "novita": "https://api.novita.ai/openai/v1",
        "huggingface": "https://router.huggingface.co/v1",
    }

    if provider in known_urls:
        logger.info(f"LLM: {provider} → {known_urls[provider]}, model={model_id}")
        return openai.LLM(model=model_id, base_url=known_urls[provider], api_key=api_key)

    # openai / openai-api — no base_url needed
    if provider in ("openai", "openai-api"):
        logger.info(f"LLM: openai, model={model_id}")
        return openai.LLM(model=model_id, api_key=api_key)

    # Unknown provider, no base_url — fall back with warning
    logger.warning(
        f"Unknown LLM provider '{provider}' with no base_url in config. "
        f"Falling back to openai.LLM(model='gpt-5.3-chat-latest'). "
        f"Set model.base_url in ~/.hermes/config.yaml or use CLAUVER_LLM_OVERRIDE=openai"
    )
    return openai.LLM(model="gpt-5.3-chat-latest")


# Provider → env var name for API key resolution
_PROVIDER_KEY_MAP = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai-api": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "zai": "GLM_API_KEY",
    "kimi-coding": "KIMI_API_KEY",
    "kimi-coding-cn": "KIMI_CN_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "minimax-cn": "MINIMAX_CN_API_KEY",
    "huggingface": "HF_TOKEN",
    "nvidia": "NVIDIA_API_KEY",
    "novita": "NOVITA_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "alibaba": "DASHSCOPE_API_KEY",
    "stepfun": "STEPFUN_API_KEY",
    "custom": None,
}


def _resolve_provider_key(provider: str, model_config: dict) -> str | None:
    """Resolve API key for a provider: check map → config → None."""
    env_var = _PROVIDER_KEY_MAP.get(provider)
    if env_var:
        key = os.getenv(env_var)
        if key:
            return key
        # Key not found — not fatal for local endpoints, warn for cloud
        logger.debug(f"Provider '{provider}' key {env_var} not found in env")

    # Try api_key from config (custom endpoints store it there)
    config_key = model_config.get("api_key")
    if config_key:
        return config_key

    return None


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
    """Return a LiveKit TTS plugin instance based on Hermes config.

    Priority: CLAUVER_TTS_OVERRIDE → Hermes config → Edge TTS (free fallback).
    """
    # --- Override check ---
    override = os.getenv("CLAUVER_TTS_OVERRIDE", "").strip().lower()
    if override:
        tts_instance = _build_tts_for_provider(override, {})
        if tts_instance:
            logger.info(f"TTS: override → {override}")
            return tts_instance
        logger.warning(f"Unknown CLAUVER_TTS_OVERRIDE '{override}', ignoring")

    # --- Read from Hermes config ---
    config = load_hermes_config()
    tts_config = config.get("tts", {})
    provider = tts_config.get("provider", "edge")

    tts_instance = _build_tts_for_provider(provider, tts_config)
    if tts_instance:
        logger.info(f"TTS: {provider} (from Hermes config)")
        return tts_instance

    # --- Fallback: Edge TTS (free) ---
    logger.warning(f"TTS provider '{provider}' not supported. Using free Edge TTS.")
    return EdgeTTSAdapter(voice="en-US-AvaMultilingualNeural")


def _get_tts_api_key(provider_env_var: str) -> str | None:
    """Resolve TTS API key: CLAUVER_TTS_API_KEY → provider-specific → None."""
    return os.getenv("CLAUVER_TTS_API_KEY") or os.getenv(provider_env_var) or None


def _build_tts_for_provider(provider: str, tts_config: dict):
    """Build TTS instance for a given provider. Returns None if unsupported."""

    if provider == "edge":
        voice = tts_config.get("edge", {}).get("voice", "en-US-AvaMultilingualNeural")
        return EdgeTTSAdapter(voice=voice)

    elif provider == "openai":
        from livekit.plugins import openai
        cfg = tts_config.get("openai", {})
        return openai.TTS(
            model=cfg.get("model", "gpt-4o-mini-tts"),
            voice=cfg.get("voice", "alloy"),
        )

    elif provider == "elevenlabs":
        from livekit.plugins import elevenlabs
        key = _get_tts_api_key("ELEVEN_API_KEY")
        if not key:
            raise RuntimeError("ElevenLabs TTS requires CLAUVER_TTS_API_KEY or ELEVEN_API_KEY")
        cfg = tts_config.get("elevenlabs", {})
        return elevenlabs.TTS(
            voice_id=cfg.get("voice_id", "pNInz6obpgDQGcFmaJgB"),
            model=cfg.get("model_id", "eleven_multilingual_v2"),
            api_key=key,
        )

    elif provider == "cartesia":
        from livekit.plugins import cartesia
        key = _get_tts_api_key("CARTESIA_API_KEY")
        if not key:
            raise RuntimeError("Cartesia TTS requires CLAUVER_TTS_API_KEY or CARTESIA_API_KEY")
        return cartesia.TTS(api_key=key)

    elif provider == "xai":
        from livekit.plugins import openai
        key = _get_tts_api_key("XAI_API_KEY")
        if not key:
            raise RuntimeError("xAI TTS requires CLAUVER_TTS_API_KEY or XAI_API_KEY")
        cfg = tts_config.get("xai", {})
        return openai.TTS(
            model="tts-1",
            voice=cfg.get("voice_id", "eve"),
            base_url="https://api.x.ai/v1",
            api_key=key,
        )

    elif provider == "gemini":
        from livekit.plugins import google
        cfg = tts_config.get("gemini", {})
        return google.TTS(
            model=cfg.get("model", "gemini-2.5-flash-preview-tts"),
            voice=cfg.get("voice", "Kore"),
        )

    elif provider == "mistral":
        from livekit.plugins import openai
        key = _get_tts_api_key("MISTRAL_API_KEY")
        if not key:
            raise RuntimeError("Mistral TTS requires CLAUVER_TTS_API_KEY or MISTRAL_API_KEY")
        cfg = tts_config.get("mistral", {})
        return openai.TTS(
            model=cfg.get("model", "voxtral-mini-tts-2603"),
            voice=cfg.get("voice_id", "c69964a6-ab8b-4f8a-9465-ec0925096ec8"),
            base_url="https://api.mistral.ai/v1",
            api_key=key,
        )

    elif provider == "deepgram":
        from livekit.plugins import deepgram
        key = _get_tts_api_key("DEEPGRAM_API_KEY")
        if not key:
            raise RuntimeError("Deepgram TTS requires CLAUVER_TTS_API_KEY or DEEPGRAM_API_KEY")
        return deepgram.TTS(api_key=key)

    return None  # unsupported


def is_streaming_tts() -> bool:
    """Return False for non-streaming TTS providers (edge), True otherwise."""
    override = os.getenv("CLAUVER_TTS_OVERRIDE", "").strip().lower()
    if override:
        return override != "edge"
    config = load_hermes_config()
    provider = config.get("tts", {}).get("provider", "edge")
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
    """Return a LiveKit STT plugin instance based on Hermes config.

    Priority: CLAUVER_STT_OVERRIDE → Hermes config → local Whisper (free fallback).
    """
    # --- Override check ---
    override = os.getenv("CLAUVER_STT_OVERRIDE", "").strip().lower()
    if override:
        stt_instance = _build_stt_for_provider(override, {})
        if stt_instance:
            logger.info(f"STT: override → {override}")
            return stt_instance
        logger.warning(f"Unknown CLAUVER_STT_OVERRIDE '{override}', ignoring")

    # --- Read from Hermes config ---
    config = load_hermes_config()
    stt_config = config.get("stt", {})
    provider = stt_config.get("provider", "local")

    stt_instance = _build_stt_for_provider(provider, stt_config)
    if stt_instance:
        return stt_instance

    # --- Fallback: local Whisper (free) ---
    logger.warning(f"STT provider '{provider}' not supported. Using free local Whisper.")
    return WhisperSTTAdapter(model="base")


def _get_stt_api_key(provider_env_var: str) -> str | None:
    """Resolve STT API key: CLAUVER_STT_API_KEY → provider-specific → None."""
    return os.getenv("CLAUVER_STT_API_KEY") or os.getenv(provider_env_var) or None


def _build_stt_for_provider(provider: str, stt_config: dict):
    """Build STT instance for a given provider. Returns None if unsupported."""

    if provider == "local":
        model = stt_config.get("local", {}).get("model", "base")
        logger.warning(
            "Local Whisper STT is configured — audio will be processed in chunks on CPU. "
            "For better call quality set CLAUVER_STT_OVERRIDE=deepgram"
        )
        logger.info(f"STT: local whisper (model={model})")
        return WhisperSTTAdapter(model=model)

    elif provider == "deepgram":
        from livekit.plugins import deepgram
        key = _get_stt_api_key("DEEPGRAM_API_KEY")
        if not key:
            raise RuntimeError("Deepgram STT requires CLAUVER_STT_API_KEY or DEEPGRAM_API_KEY")
        logger.info("STT: deepgram")
        return deepgram.STT(api_key=key)

    elif provider == "openai":
        from livekit.plugins import openai
        cfg = stt_config.get("openai", {})
        logger.info("STT: openai")
        return openai.STT(model=cfg.get("model", "whisper-1"))

    elif provider == "elevenlabs":
        from livekit.plugins import elevenlabs
        key = _get_stt_api_key("ELEVEN_API_KEY")
        if not key:
            raise RuntimeError("ElevenLabs STT requires CLAUVER_STT_API_KEY or ELEVEN_API_KEY")
        logger.info("STT: elevenlabs")
        return elevenlabs.STT(api_key=key)

    elif provider == "mistral":
        from livekit.plugins import openai
        key = _get_stt_api_key("MISTRAL_API_KEY")
        if not key:
            raise RuntimeError("Mistral STT requires CLAUVER_STT_API_KEY or MISTRAL_API_KEY")
        cfg = stt_config.get("mistral", {})
        logger.info("STT: mistral")
        return openai.STT(
            model=cfg.get("model", "voxtral-mini-latest"),
            base_url="https://api.mistral.ai/v1",
            api_key=key,
        )

    return None  # unsupported
