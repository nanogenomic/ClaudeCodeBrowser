#!/usr/bin/env python3
"""
ClaudeCodeBrowser Native Messaging Host

This script acts as a bridge between the Firefox extension and the MCP server.
It receives messages from the extension via native messaging and forwards them
to the MCP server via HTTP or WebSocket.

Features:
- Auto-starts MCP server if not running
- Monitors server health and restarts on failure
- Self-healing with exponential backoff
- No external process managers required
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
import signal
import subprocess
from pathlib import Path
from datetime import datetime

# Configure logging
LOG_DIR = Path.home() / '.claudecodebrowser' / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'native_host.log'

# Rotate log if too large (>5MB)
if LOG_FILE.exists() and LOG_FILE.stat().st_size > 5 * 1024 * 1024:
    backup = LOG_FILE.with_suffix('.log.old')
    if backup.exists():
        backup.unlink()
    LOG_FILE.rename(backup)

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

# Health monitoring settings
HEALTH_CHECK_INTERVAL = 10  # seconds
MAX_RESTART_ATTEMPTS = 10
BACKOFF_BASE = 2  # seconds, exponential backoff

# Message queues for async communication
incoming_queue = queue.Queue()
outgoing_queue = queue.Queue()

# Server process tracking
server_process = None
server_pid_file = LOG_DIR.parent / 'mcp_server.pid'
restart_attempts = 0
last_restart_time = 0
health_monitor_running = True


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
    global server_process, restart_attempts, last_restart_time

    # Check backoff
    now = time.time()
    if restart_attempts > 0:
        backoff_time = min(BACKOFF_BASE ** restart_attempts, 60)  # Cap at 60 seconds
        time_since_last = now - last_restart_time
        if time_since_last < backoff_time:
            logger.debug(f"Backoff: waiting {backoff_time - time_since_last:.1f}s before restart")
            return False

    # Reset attempts after 5 minutes of stability
    if restart_attempts > 0 and now - last_restart_time > 300:
        logger.info("Resetting restart counter after stability period")
        restart_attempts = 0

    if restart_attempts >= MAX_RESTART_ATTEMPTS:
        logger.error(f"Max restart attempts ({MAX_RESTART_ATTEMPTS}) reached. Manual intervention required.")
        return False

    # Find server script - check multiple locations
    possible_paths = [
        Path(__file__).parent.parent / 'mcp-server' / 'server.py',
        Path.home() / '.claudecodebrowser' / 'mcp-server' / 'server.py',
    ]

    mcp_server_path = None
    for path in possible_paths:
        if path.exists():
            mcp_server_path = path
            break

    if not mcp_server_path:
        logger.error(f"MCP server script not found in any location")
        return False

    try:
        # Start server as a detached subprocess
        server_process = subprocess.Popen(
            [sys.executable, str(mcp_server_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True  # Detach from parent process
        )

        restart_attempts += 1
        last_restart_time = time.time()

        logger.info(f"Started MCP server (PID: {server_process.pid}, attempt #{restart_attempts})")

        # Save PID for tracking
        try:
            with open(server_pid_file, 'w') as f:
                f.write(str(server_process.pid))
        except Exception:
            pass

        # Wait briefly for server to start
        for _ in range(15):  # Try for up to 3 seconds
            time.sleep(0.2)
            if check_mcp_server():
                logger.info("MCP server is now available")
                restart_attempts = 0  # Reset on successful start
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

    # Check if this is a response to a screenshot command - save it!
    if message.get('success') and message.get('data') and 'requestId' in message:
        # This looks like a screenshot response - save it
        logger.info("Received screenshot data, saving...")
        save_result = handle_local_command({
            'action': 'saveScreenshot',
            'data': message.get('data'),
            'filename': f'screenshot_{int(time.time())}.png'
        })
        if save_result:
            logger.info(f"Screenshot saved: {save_result.get('filepath')}")
            # Also forward the response to the server
            forward_response_to_server(message)
            return save_result

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


def forward_response_to_server(response):
    """Forward a response from the extension to the MCP server."""
    import urllib.request
    import urllib.error

    try:
        url = f'{MCP_SERVER_URL}/browser/response'
        data = json.dumps(response).encode('utf-8')

        req = urllib.request.Request(
            url,
            data=data,
            headers={'Content-Type': 'application/json'}
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))

    except Exception as e:
        logger.error(f"Failed to forward response to server: {e}")
        return None


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


def poll_for_commands():
    """Poll MCP server for pending commands and forward to extension."""
    import urllib.request
    import urllib.error

    consecutive_failures = 0

    while health_monitor_running:
        try:
            url = f'{MCP_SERVER_URL}/browser/poll'
            req = urllib.request.Request(url)

            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                consecutive_failures = 0  # Reset on success

                if data.get('command'):
                    command = data['command']
                    logger.info(f"Got command from server: {command.get('action')}")
                    # Forward command to extension
                    send_message(command)

        except urllib.error.URLError:
            consecutive_failures += 1
            # Server not available - health monitor will handle restart
            if consecutive_failures == 3:
                logger.warning("Poll: MCP server not responding (health monitor will handle)")
        except Exception as e:
            logger.debug(f"Poll error: {e}")

        time.sleep(0.5)  # Poll every 500ms


def health_monitor_thread():
    """Background thread that monitors MCP server health and restarts if needed."""
    global health_monitor_running, restart_attempts

    logger.info("Health monitor started")
    consecutive_failures = 0
    last_healthy = time.time()

    while health_monitor_running:
        try:
            time.sleep(HEALTH_CHECK_INTERVAL)

            if not health_monitor_running:
                break

            # Check server health
            if check_mcp_server():
                if consecutive_failures > 0:
                    logger.info(f"MCP server recovered after {consecutive_failures} failures")
                consecutive_failures = 0
                last_healthy = time.time()
                restart_attempts = 0  # Reset on confirmed health
            else:
                consecutive_failures += 1
                logger.warning(f"Health check failed ({consecutive_failures} consecutive)")

                # Attempt restart after 2 consecutive failures
                if consecutive_failures >= 2:
                    logger.info("Attempting to restart MCP server...")

                    # Kill stale process if port is in use
                    if is_port_in_use():
                        logger.info("Killing stale process on port")
                        kill_existing_server()
                        time.sleep(0.5)

                    if start_mcp_server():
                        logger.info("MCP server restart initiated")
                        consecutive_failures = 0
                    else:
                        logger.error("Failed to restart MCP server")

        except Exception as e:
            logger.error(f"Health monitor error: {e}")

    logger.info("Health monitor stopped")


def shutdown():
    """Clean shutdown of all threads."""
    global health_monitor_running
    logger.info("Shutting down...")
    health_monitor_running = False


def main():
    """Main entry point."""
    global health_monitor_running

    logger.info("=" * 60)
    logger.info("ClaudeCodeBrowser Native Host starting...")
    logger.info(f"MCP Server URL: {MCP_SERVER_URL}")
    logger.info(f"Health check interval: {HEALTH_CHECK_INTERVAL}s")
    logger.info("=" * 60)

    # Setup signal handlers for clean shutdown
    def signal_handler(signum, frame):
        shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Auto-start MCP server if not running
    ensure_mcp_server()

    logger.info(f"MCP Server available: {check_mcp_server()}")

    # Start output thread
    output_handler = threading.Thread(target=output_thread, daemon=True, name="output")
    output_handler.start()

    # Start polling thread for commands from MCP server
    poll_handler = threading.Thread(target=poll_for_commands, daemon=True, name="poll")
    poll_handler.start()

    # Start health monitor thread - this is the key for auto-restart!
    health_handler = threading.Thread(target=health_monitor_thread, daemon=True, name="health")
    health_handler.start()
    logger.info("Health monitor thread started - will auto-restart server on crashes")

    # Process messages in main thread
    while health_monitor_running:
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

    shutdown()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted, exiting")
        shutdown()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        shutdown()
        sys.exit(1)
