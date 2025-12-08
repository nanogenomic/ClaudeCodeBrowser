#!/bin/bash
#
# ClaudeCodeBrowser Uninstallation Script
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

INSTALL_DIR="$HOME/.claudecodebrowser"
FIREFOX_NATIVE_MANIFESTS_DIR="$HOME/.mozilla/native-messaging-hosts"

echo -e "${YELLOW}ClaudeCodeBrowser Uninstaller${NC}"
echo ""

read -p "This will remove ClaudeCodeBrowser. Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# Remove native messaging manifest
if [ -f "$FIREFOX_NATIVE_MANIFESTS_DIR/claudecodebrowser.json" ]; then
    rm "$FIREFOX_NATIVE_MANIFESTS_DIR/claudecodebrowser.json"
    echo -e "${GREEN}✓ Removed Firefox native messaging manifest${NC}"
fi

# Remove symlinks
if [ -L "$HOME/bin/claudecodebrowser-server" ]; then
    rm "$HOME/bin/claudecodebrowser-server"
    echo -e "${GREEN}✓ Removed symlink: claudecodebrowser-server${NC}"
fi

if [ -L "$HOME/bin/browser-agent" ]; then
    rm "$HOME/bin/browser-agent"
    echo -e "${GREEN}✓ Removed symlink: browser-agent${NC}"
fi

# Ask about screenshots
if [ -d "$INSTALL_DIR/screenshots" ] && [ "$(ls -A "$INSTALL_DIR/screenshots" 2>/dev/null)" ]; then
    read -p "Remove saved screenshots? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$INSTALL_DIR/screenshots"
        echo -e "${GREEN}✓ Removed screenshots${NC}"
    else
        echo "Screenshots preserved at: $INSTALL_DIR/screenshots"
    fi
fi

# Remove installation directory
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    echo -e "${GREEN}✓ Removed installation directory${NC}"
fi

echo ""
echo -e "${GREEN}ClaudeCodeBrowser has been uninstalled.${NC}"
echo ""
echo "Note: You may need to manually remove the Firefox extension"
echo "      from about:addons if it was installed permanently."
