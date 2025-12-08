#!/usr/bin/env python3
"""
ClaudeCodeBrowser Native Messaging Host

This script acts as a bridge between the Firefox extension and the MCP server.
It receives messages from the extension via native messaging and forwards them
to the MCP server via HTTP or WebSocket.
"""

import sys
import json
import struct
import threading
import queue
import logging
import os
import socket
import time
from pathlib import Path

# Configure logging
LOG_DIR = Path.home() / '.claudecodebrowser' / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'native_host.log'

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

# Configuration
MCP_SERVER_HOST = os.environ.get('CLAUDE_MCP_HOST', 'localhost')
MCP_SERVER_PORT = int(os.environ.get('CLAUDE_MCP_PORT', '8765'))
MCP_SERVER_URL = f'http://{MCP_SERVER_HOST}:{MCP_SERVER_PORT}'

# Message queues for async communication
incoming_queue = queue.Queue()
outgoing_queue = queue.Queue()


def read_message():
    """Read a message from stdin using native messaging protocol."""
    try:
        # Read message length (4 bytes)
        raw_length = sys.stdin.buffer.read(4)
        if len(raw_length) == 0:
            return None

        message_length = struct.unpack('@I', raw_length)[0]

        # Read message content
        message = sys.stdin.buffer.read(message_length).decode('utf-8')
        return json.loads(message)
    except Exception as e:
        logger.error(f"Error reading message: {e}")
        return None


def send_message(message):
    """Send a message to stdout using native messaging protocol."""
    try:
        encoded = json.dumps(message).encode('utf-8')
        length = struct.pack('@I', len(encoded))

        sys.stdout.buffer.write(length)
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()

        logger.debug(f"Sent message: {message}")
    except Exception as e:
        logger.error(f"Error sending message: {e}")


def forward_to_mcp_server(message):
    """Forward a message to the MCP server via HTTP."""
    import urllib.request
    import urllib.error

    try:
        url = f'{MCP_SERVER_URL}/browser/command'
        data = json.dumps(message).encode('utf-8')

        req = urllib.request.Request(
            url,
            data=data,
            headers={'Content-Type': 'application/json'}
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result

    except urllib.error.URLError as e:
        logger.error(f"Failed to connect to MCP server: {e}")
        return {'success': False, 'error': f'MCP server connection failed: {str(e)}'}
    except Exception as e:
        logger.error(f"Error forwarding to MCP server: {e}")
        return {'success': False, 'error': str(e)}


def check_mcp_server():
    """Check if MCP server is running and responding."""
    import urllib.request
    import urllib.error

    try:
        # First check if port is open
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((MCP_SERVER_HOST, MCP_SERVER_PORT))
        sock.close()

        if result != 0:
            return False

        # Port is open, now verify server is actually responding
        url = f'{MCP_SERVER_URL}/health'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as response:
            data = response.read().decode('utf-8')
            return 'ok' in data.lower()

    except Exception:
        return False


def kill_existing_server():
    """Kill any existing MCP server process on the port."""
    import subprocess

    try:
        # Find process using the port
        result = subprocess.run(
            ['lsof', '-ti', f':{MCP_SERVER_PORT}'],
            capture_output=True,
            text=True
        )

        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                try:
                    pid = int(pid.strip())
                    logger.info(f"Killing existing process on port {MCP_SERVER_PORT}: PID {pid}")
                    os.kill(pid, 9)  # SIGKILL
                except (ValueError, ProcessLookupError):
                    pass

            # Wait briefly for port to be released
            time.sleep(0.5)
            return True

    except FileNotFoundError:
        # lsof not available, try fuser
        try:
            result = subprocess.run(
                ['fuser', '-k', f'{MCP_SERVER_PORT}/tcp'],
                capture_output=True
            )
            time.sleep(0.5)
            return True
        except FileNotFoundError:
            logger.warning("Neither lsof nor fuser available to kill existing server")

    except Exception as e:
        logger.warning(f"Failed to kill existing server: {e}")

    return False


def start_mcp_server():
    """Start the MCP server if it's not running."""
    import subprocess

    mcp_server_path = Path(__file__).parent.parent / 'mcp-server' / 'server.py'

    if not mcp_server_path.exists():
        logger.error(f"MCP server script not found at {mcp_server_path}")
        return False

    try:
        # Start server as a detached subprocess
        process = subprocess.Popen(
            [sys.executable, str(mcp_server_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True  # Detach from parent process
        )
        logger.info(f"Started MCP server (PID: {process.pid})")

        # Wait briefly for server to start
        for _ in range(10):  # Try for up to 2 seconds
            time.sleep(0.2)
            if check_mcp_server():
                logger.info("MCP server is now available")
                return True

        logger.warning("MCP server started but not yet responding")
        return True  # Server started, may just need more time

    except Exception as e:
        logger.error(f"Failed to start MCP server: {e}")
        return False


def is_port_in_use():
    """Check if the MCP server port is in use (regardless of whether it responds)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((MCP_SERVER_HOST, MCP_SERVER_PORT))
        sock.close()
        return result == 0
    except Exception:
        return False


def ensure_mcp_server():
    """Ensure MCP server is running, start it if not."""
    # Check if server is running and responding
    if check_mcp_server():
        logger.info("MCP server already running and responding")
        return True

    # Check if port is in use but server not responding (stale process)
    if is_port_in_use():
        logger.warning("Port in use but server not responding - killing stale process")
        kill_existing_server()

    logger.info("MCP server not running, attempting to start...")
    return start_mcp_server()


def handle_local_command(message):
    """Handle commands that don't need MCP server."""
    action = message.get('action')

    if action == 'ping':
        return {'success': True, 'pong': True, 'timestamp': time.time()}

    elif action == 'status':
        mcp_available = check_mcp_server()
        return {
            'success': True,
            'mcp_server': {
                'url': MCP_SERVER_URL,
                'available': mcp_available
            },
            'native_host': {
                'version': '1.0.0',
                'pid': os.getpid()
            }
        }

    elif action == 'saveScreenshot':
        # Save screenshot to file
        try:
            data = message.get('data', '')
            filename = message.get('filename', f'screenshot_{int(time.time())}.png')

            # Use configurable screenshots directory (default: /tmp/claudecodebrowser/screenshots)
            # This ensures screenshots are accessible from any mount point (e.g., /mnt/backup/)
            default_dir = Path('/tmp/claudecodebrowser/screenshots')
            screenshots_dir = Path(os.environ.get('CLAUDE_BROWSER_SCREENSHOTS_DIR', str(default_dir)))
            screenshots_dir.mkdir(parents=True, exist_ok=True)

            filepath = screenshots_dir / filename

            # Handle base64 data URL
            if data.startswith('data:image'):
                import base64
                header, encoded = data.split(',', 1)
                image_data = base64.b64decode(encoded)
            else:
                import base64
                image_data = base64.b64decode(data)

            with open(filepath, 'wb') as f:
                f.write(image_data)

            return {'success': True, 'filepath': str(filepath)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    return None


def process_message(message):
    """Process an incoming message from the extension."""
    logger.info(f"Processing message: {message.get('action', 'unknown')}")

    # Try to handle locally first
    local_result = handle_local_command(message)
    if local_result is not None:
        return local_result

    # Forward to MCP server
    if check_mcp_server():
        return forward_to_mcp_server(message)
    else:
        return {
            'success': False,
            'error': 'MCP server is not available. Please start the server first.',
            'requestId': message.get('requestId')
        }


def input_thread():
    """Thread for reading messages from the extension."""
    while True:
        message = read_message()
        if message is None:
            logger.info("Extension disconnected")
            break

        logger.debug(f"Received message: {message}")
        incoming_queue.put(message)


def output_thread():
    """Thread for sending messages to the extension."""
    while True:
        try:
            message = outgoing_queue.get(timeout=1)
            send_message(message)
        except queue.Empty:
            continue


def main():
    """Main entry point."""
    logger.info("ClaudeCodeBrowser Native Host starting...")
    logger.info(f"MCP Server URL: {MCP_SERVER_URL}")

    # Auto-start MCP server if not running
    ensure_mcp_server()

    logger.info(f"MCP Server available: {check_mcp_server()}")

    # Start output thread
    output_handler = threading.Thread(target=output_thread, daemon=True)
    output_handler.start()

    # Process messages in main thread
    while True:
        message = read_message()
        if message is None:
            logger.info("Input stream closed, exiting")
            break

        logger.debug(f"Received: {message}")

        # Process and respond
        response = process_message(message)

        # Include request ID for correlation
        if 'requestId' in message:
            response['requestId'] = message['requestId']

        send_message(response)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted, exiting")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
