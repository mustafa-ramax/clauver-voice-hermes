"""
Test script for hermes_bridge.py — verifies provider detection and object creation.
Does NOT make any actual API calls.
"""

from hermes_bridge import load_hermes_config, build_llm, build_tts, build_stt, is_streaming_tts


def main():
    print("=== Hermes Config Bridge Test ===\n")

    # 1. Load config and detect providers
    config = load_hermes_config()
    llm_provider = config.get("model", {}).get("provider", "unknown")
    llm_model = config.get("model", {}).get("default", "unknown")
    tts_provider = config.get("tts", {}).get("provider", "unknown")
    stt_provider = config.get("stt", {}).get("provider", "unknown")

    print(f"LLM provider: {llm_provider} (model: {llm_model})")
    print(f"TTS provider: {tts_provider}")
    print(f"STT provider: {stt_provider}")
    print()

    # 2. Build each plugin instance
    print("--- Building LLM ---")
    try:
        llm = build_llm()
        print(f"  ✓ {type(llm).__module__}.{type(llm).__name__}")
    except Exception as e:
        print(f"  ✗ Failed: {e}")

    print("--- Building TTS ---")
    try:
        tts = build_tts()
        print(f"  ✓ {type(tts).__module__}.{type(tts).__name__}")
    except Exception as e:
        print(f"  ✗ Failed: {e}")

    print("--- Building STT ---")
    try:
        stt = build_stt()
        print(f"  ✓ {type(stt).__module__}.{type(stt).__name__}")
    except Exception as e:
        print(f"  ✗ Failed: {e}")

    print()
    print(f"is_streaming_tts(): {is_streaming_tts()}")
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
