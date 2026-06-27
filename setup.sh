#!/bin/bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════
# Clauver Telephony — Setup Script
# One command to install AI phone calling for Hermes Agent.
# Works on: macOS, Linux (Ubuntu/Debian/Arch), Windows (Git Bash)
# ═══════════════════════════════════════════════════════════════

INSTALL_DIR="$HOME/.clauver"
REPO="https://github.com/mustafa-ramax/clauver-voice-hermes.git"

echo "🔧 Setting up Clauver Telephony..."
echo ""

# --- Detect OS ---
case "$OSTYPE" in
    msys*|cygwin*|win32*) IS_WINDOWS=true ;;
    *)                    IS_WINDOWS=false ;;
esac

# --- Resolve Hermes home ---
if command -v hermes &>/dev/null; then
    HERMES_HOME=$(dirname "$(hermes config path 2>/dev/null)" 2>/dev/null) || HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
else
    HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
fi
echo "   Hermes home: $HERMES_HOME"

# --- Check prerequisites ---
if ! command -v git &>/dev/null; then
    echo "❌ git not found. Install git first."
    exit 1
fi

if ! command -v ffmpeg &>/dev/null; then
    echo "⚠️  ffmpeg not found. Edge TTS (free voice) requires it."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "   Install: brew install ffmpeg"
    elif [[ "$IS_WINDOWS" == true ]]; then
        echo "   Install: winget install ffmpeg"
    else
        echo "   Install: sudo apt install ffmpeg"
    fi
    echo ""
fi

# --- Clone or update repo ---
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "   Updating existing install at $INSTALL_DIR..."
    cd "$INSTALL_DIR"
    git pull --quiet 2>/dev/null || true
else
    # Remove broken install (dir exists but not a git repo)
    [ -d "$INSTALL_DIR" ] && rm -rf "$INSTALL_DIR"
    echo "   Cloning Clauver to $INSTALL_DIR..."
    git clone --quiet "$REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# --- Determine python/pip paths based on OS ---
if [[ "$IS_WINDOWS" == true ]]; then
    VENV_PYTHON="$INSTALL_DIR/.venv/Scripts/python.exe"
    VENV_PIP="$INSTALL_DIR/.venv/Scripts/pip.exe"
else
    VENV_PYTHON="$INSTALL_DIR/.venv/bin/python"
    VENV_PIP="$INSTALL_DIR/.venv/bin/pip"
fi

# --- Remove broken venv (exists but python binary missing) ---
if [ -d ".venv" ] && [ ! -f "$VENV_PYTHON" ]; then
    echo "   Removing broken venv..."
    rm -rf .venv
fi

# --- Create venv + install deps ---
echo "   Installing dependencies..."

if [ ! -d ".venv" ]; then
    if command -v uv &>/dev/null; then
        uv venv .venv --quiet
    elif python3 -m venv .venv 2>/dev/null; then
        true  # success
    else
        echo ""
        echo "❌ Cannot create virtual environment."
        if [[ "$OSTYPE" == "linux"* ]]; then
            PY_VERSION=$(python3 --version 2>/dev/null | grep -oP '\d+\.\d+' || echo "3")
            echo "   Fix: sudo apt install python${PY_VERSION}-venv"
        elif [[ "$IS_WINDOWS" == true ]]; then
            echo "   Fix: Install Python from python.org (includes venv)"
        else
            echo "   Fix: Install Python 3.11+ from python.org or brew install python"
        fi
        echo "   Or install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
        echo "   Then re-run this script."
        exit 1
    fi
fi

# Install dependencies
if command -v uv &>/dev/null; then
    uv pip install --quiet -r requirements.txt -p "$VENV_PYTHON"
else
    "$VENV_PIP" install --quiet --upgrade pip
    "$VENV_PIP" install --quiet -r requirements.txt
fi

# Pre-download Whisper STT model so first call works instantly
if [ -z "${CLAUVER_STT_OVERRIDE:-}" ]; then
    echo "   Pre-downloading Whisper STT model (~142MB, one-time)..."
    "$VENV_PYTHON" -c "
from faster_whisper import WhisperModel
WhisperModel('base', device='cpu', compute_type='int8')
print('   \u2713 Whisper model cached')
" 2>/dev/null || echo "   ⚠️  Whisper preload skipped (will download on first worker start)"
fi

# --- Generate .env if not exists ---
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "   Created .env from template"
else
    echo "   .env already exists (keeping your config)"
fi

# --- Register MCP server in Hermes ---
if command -v hermes &>/dev/null; then
    if hermes mcp list 2>/dev/null | grep -q "clauver"; then
        echo "   MCP server already registered"
    else
        echo "   Registering MCP server in Hermes..."
        hermes mcp add clauver --command "$VENV_PYTHON" -- -m mcp_bridge.server 2>/dev/null || {
            echo "   ⚠️  Auto-registration failed. Add manually:"
            echo "      hermes mcp add clauver --command \"$VENV_PYTHON\" -- -m mcp_bridge.server"
        }
    fi
else
    echo "   ⚠️  'hermes' CLI not found. Register MCP server manually:"
    echo "      hermes mcp add clauver --command \"$VENV_PYTHON\" -- -m mcp_bridge.server"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "✅ Clauver installed at: $INSTALL_DIR"
echo ""
echo "👉 Next step — connect your phone number:"
echo "   cd $INSTALL_DIR && .venv/bin/python scripts/provision_sip.py"
echo ""
echo "   This connects your Twilio number to LiveKit cloud automatically."
echo "   You'll need your Twilio + LiveKit credentials (both free to sign up)."
echo ""
echo "   Or edit .env manually if you already have a SIP trunk."
echo ""
echo "   Then restart Hermes and say: \"Call +61... and tell them ...\""
echo "═══════════════════════════════════════════════════════════════"
