#!/bin/bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════
# Clauver Telephony — Setup Script
# One command to install AI phone calling for Hermes Agent.
# ═══════════════════════════════════════════════════════════════

INSTALL_DIR="$HOME/.clauver"
REPO="https://github.com/mustafa-ramax/clauver-voice-hermes.git"

echo "🔧 Setting up Clauver Telephony..."
echo ""

# --- Resolve Hermes home ---
if command -v hermes &>/dev/null; then
    HERMES_HOME=$(dirname "$(hermes config path 2>/dev/null)" 2>/dev/null || echo "${HERMES_HOME:-$HOME/.hermes}")
else
    HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
fi
echo "   Hermes home: $HERMES_HOME"

# --- Check prerequisites ---
if ! command -v python3 &>/dev/null; then
    echo "❌ python3 not found. Install Python 3.11+ first."
    exit 1
fi

if ! command -v git &>/dev/null; then
    echo "❌ git not found. Install git first."
    exit 1
fi

if ! command -v ffmpeg &>/dev/null; then
    echo "⚠️  ffmpeg not found. Edge TTS requires it."
    echo "   Install: brew install ffmpeg (macOS) / apt install ffmpeg (Linux)"
    echo ""
fi

# --- Clone or update repo ---
if [ -d "$INSTALL_DIR" ]; then
    echo "   Updating existing install at $INSTALL_DIR..."
    cd "$INSTALL_DIR"
    git pull --quiet 2>/dev/null || true
else
    echo "   Cloning Clauver to $INSTALL_DIR..."
    git clone --quiet "$REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# --- Create venv + install deps ---
echo "   Installing dependencies..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

# --- Generate .env if not exists ---
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "   Created .env from template"
else
    echo "   .env already exists (keeping your config)"
fi

# --- Register MCP server in Hermes ---
PYTHON_PATH="$INSTALL_DIR/.venv/bin/python"
if command -v hermes &>/dev/null; then
    # Check if already registered
    if hermes mcp list 2>/dev/null | grep -q "clauver"; then
        echo "   MCP server already registered in Hermes"
    else
        echo "   Registering MCP server in Hermes..."
        hermes mcp add clauver --command "$PYTHON_PATH" -- -m mcp_bridge.server 2>/dev/null || \
            echo "   ⚠️  Auto-registration failed. Add manually to ~/.hermes/config.yaml:"
            echo "      mcp_servers:"
            echo "        clauver:"
            echo "          command: $PYTHON_PATH"
            echo "          args: [\"-m\", \"mcp_bridge.server\"]"
    fi
else
    echo "   ⚠️  'hermes' CLI not found. Add MCP server manually to your Hermes config:"
    echo "      mcp_servers:"
    echo "        clauver:"
    echo "          command: $PYTHON_PATH"
    echo "          args: [\"-m\", \"mcp_bridge.server\"]"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "✅ Clauver installed at: $INSTALL_DIR"
echo ""
echo "👉 Next step: Fill in your LiveKit keys:"
echo "   ${EDITOR:-nano} $INSTALL_DIR/.env"
echo ""
echo "   You need 4 values "Free Subscription" from https://cloud.livekit.io:"
echo "   • LIVEKIT_URL"
echo "   • LIVEKIT_API_KEY"
echo "   • LIVEKIT_API_SECRET"
echo "   • SIP_OUTBOUND_TRUNK_ID"
echo ""
echo "   Then restart Hermes and say: \"Call +61... and tell them ...\""
echo "═══════════════════════════════════════════════════════════════"
