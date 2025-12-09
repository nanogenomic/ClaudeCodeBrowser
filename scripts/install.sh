#!/bin/bash
#
# ClaudeCodeBrowser Installation Script
#
# This script installs the ClaudeCodeBrowser components:
# - Firefox extension
# - Native messaging host
# - MCP server
# - Browser automation agent
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="$HOME/.claudecodebrowser"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIREFOX_NATIVE_MANIFESTS_DIR="$HOME/.mozilla/native-messaging-hosts"

echo -e "${BLUE}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       ClaudeCodeBrowser Installation Script                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check dependencies
echo -e "${YELLOW}Checking dependencies...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is required but not installed.${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "${GREEN}✓ Python $PYTHON_VERSION found${NC}"

# Check for Firefox
if command -v firefox &> /dev/null; then
    FIREFOX_VERSION=$(firefox --version 2>/dev/null | head -n1)
    echo -e "${GREEN}✓ $FIREFOX_VERSION found${NC}"
else
    echo -e "${YELLOW}⚠ Firefox not found in PATH${NC}"
fi

# Create installation directory
echo -e "\n${YELLOW}Creating installation directory...${NC}"
mkdir -p "$INSTALL_DIR"/{native-host,mcp-server,agent,screenshots,logs}
echo -e "${GREEN}✓ Created $INSTALL_DIR${NC}"

# Copy files
echo -e "\n${YELLOW}Installing components...${NC}"

# Copy native host
cp "$SCRIPT_DIR/native-host/claudecodebrowser_host.py" "$INSTALL_DIR/native-host/"
chmod +x "$INSTALL_DIR/native-host/claudecodebrowser_host.py"
echo -e "${GREEN}✓ Native messaging host installed${NC}"

# Copy MCP server
cp "$SCRIPT_DIR/mcp-server/server.py" "$INSTALL_DIR/mcp-server/"
cp "$SCRIPT_DIR/mcp-server/mcp_config.json" "$INSTALL_DIR/mcp-server/"
chmod +x "$INSTALL_DIR/mcp-server/server.py"
echo -e "${GREEN}✓ MCP server installed${NC}"

# Copy agent
cp "$SCRIPT_DIR/agent/browser_agent.py" "$INSTALL_DIR/agent/"
chmod +x "$INSTALL_DIR/agent/browser_agent.py"
echo -e "${GREEN}✓ Browser agent installed${NC}"

# Install native messaging manifest for Firefox
echo -e "\n${YELLOW}Installing Firefox native messaging manifest...${NC}"
mkdir -p "$FIREFOX_NATIVE_MANIFESTS_DIR"

cat > "$FIREFOX_NATIVE_MANIFESTS_DIR/claudecodebrowser.json" << EOF
{
  "name": "claudecodebrowser",
  "description": "ClaudeCodeBrowser Native Messaging Host",
  "path": "$INSTALL_DIR/native-host/claudecodebrowser_host.py",
  "type": "stdio",
  "allowed_extensions": [
    "claudecodebrowser@ligandal.com"
  ]
}
EOF
echo -e "${GREEN}✓ Firefox native messaging manifest installed${NC}"

# Create convenience scripts
echo -e "\n${YELLOW}Creating convenience scripts...${NC}"

# Start server script
cat > "$INSTALL_DIR/start-server.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")/mcp-server"
python3 server.py
EOF
chmod +x "$INSTALL_DIR/start-server.sh"

# Agent script
cat > "$INSTALL_DIR/browser-agent" << EOF
#!/bin/bash
python3 "$INSTALL_DIR/agent/browser_agent.py" "\$@"
EOF
chmod +x "$INSTALL_DIR/browser-agent"

# Create symlinks in ~/bin if it exists
if [ -d "$HOME/bin" ]; then
    ln -sf "$INSTALL_DIR/start-server.sh" "$HOME/bin/claudecodebrowser-server"
    ln -sf "$INSTALL_DIR/browser-agent" "$HOME/bin/browser-agent"
    echo -e "${GREEN}✓ Created symlinks in ~/bin${NC}"
fi

echo -e "${GREEN}✓ Convenience scripts created${NC}"

# Install Python dependencies
echo -e "\n${YELLOW}Checking Python dependencies...${NC}"

# Check for websockets
if python3 -c "import websockets" 2>/dev/null; then
    echo -e "${GREEN}✓ websockets module found${NC}"
else
    echo -e "${YELLOW}Installing websockets module...${NC}"
    pip3 install --user websockets || echo -e "${YELLOW}⚠ Could not install websockets (WebSocket support will be disabled)${NC}"
fi

# Print Firefox extension installation instructions
echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}Firefox Extension Installation:${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "The Firefox extension needs to be installed manually:"
echo ""
echo "Option 1: Temporary installation (for testing)"
echo "  1. Open Firefox and navigate to: about:debugging"
echo "  2. Click 'This Firefox' in the left sidebar"
echo "  3. Click 'Load Temporary Add-on...'"
echo "  4. Navigate to: $SCRIPT_DIR/extension"
echo "  5. Select 'manifest.json'"
echo ""
echo "Option 2: Permanent installation (requires signing)"
echo "  1. Package the extension: cd $SCRIPT_DIR/extension && zip -r ../claudecodebrowser.xpi *"
echo "  2. Sign at: https://addons.mozilla.org/developers/"
echo "  3. Or use about:config to set 'xpinstall.signatures.required' to false"
echo "     (only works in Firefox Developer Edition or Nightly)"
echo ""

# Print Claude Code MCP configuration
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}Claude Code MCP Configuration:${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "Add this to your Claude Code settings (~/.claude/settings.json):"
echo ""
echo '{
  "mcpServers": {
    "claudecodebrowser": {
      "command": "python3",
      "args": ["'$INSTALL_DIR'/mcp-server/server.py"]
    }
  }
}'
echo ""

# Print usage instructions
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}Usage:${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "1. Start the MCP server:"
echo "   $INSTALL_DIR/start-server.sh"
echo ""
echo "2. Use the browser agent (interactive mode):"
echo "   $INSTALL_DIR/browser-agent -i"
echo ""
echo "3. Take a screenshot:"
echo "   $INSTALL_DIR/browser-agent --screenshot"
echo ""
echo "4. Navigate to a URL:"
echo "   $INSTALL_DIR/browser-agent --navigate https://example.com"
echo ""

# Built-in resilience info
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}Auto-Restart & Crash Recovery (Built-in):${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "The extension includes built-in resilience:"
echo "  • Native host auto-starts MCP server when needed"
echo "  • Health monitoring restarts server on crashes"
echo "  • Exponential backoff prevents restart storms"
echo "  • Extension auto-reconnects to native host"
echo ""
echo "No external process managers (PM2/systemd) required!"
echo ""

echo -e "${GREEN}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       Installation complete!                                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
