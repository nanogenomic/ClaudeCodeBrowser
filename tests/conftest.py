import importlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MCP_DIR = ROOT / "mcp-server"


@pytest.fixture(scope="session")
def temp_home(tmp_path_factory):
    """Point logs, token and screenshots of the imported modules at a temp home."""
    home = tmp_path_factory.mktemp("home")
    for var in ("HOME", "USERPROFILE"):
        os.environ[var] = str(home)
    os.environ["CLAUDE_BROWSER_SCREENSHOTS_DIR"] = str(home / "screenshots")
    return home


@pytest.fixture(scope="session")
def server(temp_home):
    """mcp-server/server.py, imported."""
    sys.path.insert(0, str(MCP_DIR))
    return importlib.import_module("server")


@pytest.fixture(scope="session")
def native_host(temp_home):
    """native-host/claudecodebrowser_host.py, imported (its main() is not run)."""
    spec = importlib.util.spec_from_file_location(
        "claudecodebrowser_host", ROOT / "native-host" / "claudecodebrowser_host.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
