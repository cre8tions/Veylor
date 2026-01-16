#!/usr/bin/env python3
"""
Veylor - High-performance WebSocket relay/reflector

Connects to remote WebSocket services and rebroadcasts messages to multiple
endpoints (WebSocket and Unix sockets) with maximum efficiency using async I/O.
"""

import asyncio
import logging
import signal
import sys
import os
import time
import uvloop
from typing import Set, Optional, Dict, Any, List
from collections import deque
import websockets
from websockets.asyncio.server import serve as ws_serve
from websockets.asyncio.client import connect as ws_connect
import yaml
import argparse

# TUI support (imported conditionally)
try:
    from veylor_tui import VeylorTUI, TUILogHandler
    TUI_AVAILABLE = True
except ImportError:
    TUI_AVAILABLE = False


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger('veylor')


class TUILoggingHandler(logging.Handler):
    """Custom logging handler that routes logs to the TUI"""

    def __init__(self, tui_handler):
        super().__init__()
        self.tui_handler = tui_handler

    def emit(self, record):
        try:
            # Get just the message without timestamp/level
            msg = record.getMessage()
            self.tui_handler.write(msg, record.levelname)
        except Exception:
            self.handleError(record)



class SourceRelay:
    """Relay for a single WebSocket source with dedicated endpoints"""

    def __init__(self, source_config: Dict[str, Any], performance_config: Dict[str, Any]):
        self.source_config = source_config
        self.performance_config = performance_config
        self.ws_clients: Set[websockets.ServerConnection] = set()
        self.unix_clients: Set[asyncio.StreamWriter] = set()
        self.running = True
        self.source_connection = None
        self.servers = []

        # Metrics tracking
        self.metrics = {
            'messages_from_source': 0,
            'messages_to_source': 0,
            'bytes_from_source': 0,
            'bytes_to_source': 0,
            'message_timestamps': deque(maxlen=50000),  # Keep last 1000 message timestamps
            'start_time': time.time(),
            'last_message_time': None,
            'source_connected_at': None,
        }

    async def broadcast_message(self, message: bytes):
        """Broadcast message to all connected clients (non-blocking)"""
        # Update metrics
        now = time.time()
        self.metrics['messages_from_source'] += 1
        self.metrics['bytes_from_source'] += len(message)
        self.metrics['last_message_time'] = now
        self.metrics['message_timestamps'].append(now)

        # Broadcast to WebSocket clients
        if self.ws_clients:
            # Use asyncio.gather for concurrent sending
            ws_tasks = []
            for client in self.ws_clients.copy():
                try:
                    ws_tasks.append(asyncio.create_task(client.send(message)))
                except Exception as e:
                    logger.error(f"Error queuing WebSocket message: {e}")
                    self.ws_clients.discard(client)

            # Wait for all sends to complete (non-blocking)
            if ws_tasks:
                results = await asyncio.gather(*ws_tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"Error sending to WebSocket client: {result}")

        # Broadcast to Unix socket clients
        if self.unix_clients:
            unix_tasks = []
            for writer in self.unix_clients.copy():
                try:
                    # Write message with length prefix for framing
                    msg_len = len(message)
                    writer.write(msg_len.to_bytes(4, byteorder='big'))
                    writer.write(message)
                    unix_tasks.append(asyncio.create_task(writer.drain()))
                except Exception as e:
                    logger.error(f"Error queuing Unix socket message: {e}")
                    self.unix_clients.discard(writer)
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except:
                        pass

            # Wait for all drains to complete
            if unix_tasks:
                await asyncio.gather(*unix_tasks, return_exceptions=True)

    async def handle_websocket_client(self, websocket, path=None):
        """Handle incoming WebSocket client connection"""
        self.ws_clients.add(websocket)
        client_addr = websocket.remote_address
        logger.info(f"WebSocket client connected: {client_addr}")

        try:
            # Listen for messages from client and forward to source
            async for message in websocket:
                if self.source_connection:
                    try:
                        # Update metrics
                        msg_bytes = message if isinstance(message, bytes) else message.encode('utf-8')
                        self.metrics['messages_to_source'] += 1
                        self.metrics['bytes_to_source'] += len(msg_bytes)

                        await self.source_connection.send(message)
                        logger.debug(f"Forwarded message from client {client_addr} to source")
                    except Exception as e:
                        logger.error(f"Error forwarding message to source: {e}")
                else:
                    logger.warning(f"Cannot forward message from {client_addr}: no source connection")
        except Exception as e:
            logger.error(f"WebSocket client error: {e}")
        finally:
            self.ws_clients.discard(websocket)
            logger.info(f"WebSocket client disconnected: {client_addr}")

    async def handle_unix_client(self, reader: asyncio.StreamReader,
                                 writer: asyncio.StreamWriter):
        """Handle incoming Unix socket client connection"""
        self.unix_clients.add(writer)
        peer = writer.get_extra_info('peername', 'unknown')
        logger.info(f"Unix socket client connected: {peer}")

        # Maximum message size (10 MB)
        MAX_MESSAGE_SIZE = 10 * 1024 * 1024

        try:
            # Listen for messages from client and forward to source
            while self.running:
                # Read 4-byte length prefix
                length_data = await reader.read(4)
                if not length_data or len(length_data) < 4:
                    break

                msg_len = int.from_bytes(length_data, byteorder='big')

                # Validate message length
                if msg_len <= 0 or msg_len > MAX_MESSAGE_SIZE:
                    logger.error(f"Invalid message length from {peer}: {msg_len}")
                    break

                # Read exact number of bytes for the message
                message = b''
                remaining = msg_len
                while remaining > 0:
                    chunk = await reader.read(min(remaining, 8192))
                    if not chunk:
                        break
                    message += chunk
                    remaining -= len(chunk)

                # Verify we received complete message
                if len(message) != msg_len:
                    logger.error(f"Incomplete message from {peer}: expected {msg_len}, got {len(message)}")
                    break

                # Forward message to source WebSocket
                if self.source_connection:
                    try:
                        # Update metrics
                        self.metrics['messages_to_source'] += 1
                        self.metrics['bytes_to_source'] += len(message)

                        await self.source_connection.send(message)
                        logger.debug(f"Forwarded message from Unix client {peer} to source")
                    except Exception as e:
                        logger.error(f"Error forwarding message to source: {e}")
                else:
                    logger.warning(f"Cannot forward message from {peer}: no source connection")
        except Exception as e:
            logger.error(f"Unix socket client error: {e}")
        finally:
            self.unix_clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass
            logger.info(f"Unix socket client disconnected: {peer}")

    async def connect_to_source(self):
        """Connect to remote WebSocket source and relay messages"""
        url = self.source_config['url']
        headers = self.source_config.get('headers', {})
        reconnect_delay = self.performance_config.get('reconnect_delay', 5)
        max_attempts = self.performance_config.get('reconnect_max_attempts', 0)

        attempt = 0
        while self.running:
            try:
                if max_attempts > 0 and attempt >= max_attempts:
                    logger.error(f"Max reconnection attempts ({max_attempts}) reached for {url}")
                    break

                if attempt > 0:
                    logger.info(f"Reconnecting to {url} (attempt {attempt + 1})...")
                    await asyncio.sleep(reconnect_delay)

                attempt += 1

                logger.info(f"Connecting to source: {url}")
                async with ws_connect(url, additional_headers=headers) as websocket:
                    self.source_connection = websocket
                    self.metrics['source_connected_at'] = time.time()
                    logger.info(f"Connected to source: {url}")
                    attempt = 0  # Reset attempt counter on successful connection

                    # Receive and broadcast messages
                    async for message in websocket:
                        if not self.running:
                            break

                        # Handle both text and binary messages
                        if isinstance(message, str):
                            message = message.encode('utf-8')

                        # Broadcast to all clients (non-blocking)
                        await self.broadcast_message(message)

            except asyncio.CancelledError:
                logger.info(f"Source connection cancelled: {url}")
                break
            except Exception as e:
                logger.error(f"Error with source {url}: {e}")
                if not self.running:
                    break

    async def start_websocket_server(self):
        """Start WebSocket rebroadcast server for this source"""
        ws_port = self.source_config.get('websocket_port')
        if not ws_port:
            return

        host = self.source_config.get('websocket_host', '0.0.0.0')

        try:
            logger.info(f"Starting WebSocket server for source {self.source_config['url']} on {host}:{ws_port}")
            server = await ws_serve(self.handle_websocket_client, host, ws_port)
            self.servers.append(server)
            logger.info(f"WebSocket server started on {host}:{ws_port}")
        except Exception as e:
            logger.error(f"Failed to start WebSocket server on {host}:{ws_port}: {e}")
            raise

    async def start_unix_server(self):
        """Start Unix socket rebroadcast server for this source"""
        socket_path = self.source_config.get('unix_socket_path')
        if not socket_path:
            return

        try:
            # Remove existing socket file if it exists
            if os.path.exists(socket_path):
                os.remove(socket_path)

            logger.info(f"Starting Unix socket server for source {self.source_config['url']} on {socket_path}")
            server = await asyncio.start_unix_server(
                self.handle_unix_client,
                path=socket_path
            )
            self.servers.append(server)
            logger.info(f"Unix socket server started on {socket_path}")
        except Exception as e:
            logger.error(f"Failed to start Unix socket server on {socket_path}: {e}")
            raise

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Calculate current metrics summary"""
        now = time.time()
        uptime = now - self.metrics['start_time']

        # Calculate messages per minute
        recent_messages = [ts for ts in self.metrics['message_timestamps'] if now - ts < 60]
        messages_per_minute = len(recent_messages)

        # Calculate average message interval (time between consecutive messages)
        avg_latency = 0.0
        if len(self.metrics['message_timestamps']) > 1:
            timestamps = list(self.metrics['message_timestamps'])
            latencies = [timestamps[i] - timestamps[i-1] for i in range(1, len(timestamps))]
            if latencies:
                avg_latency = sum(latencies) / len(latencies)

        # Calculate source uptime
        source_uptime = 0.0
        if self.metrics['source_connected_at']:
            source_uptime = now - self.metrics['source_connected_at']

        return {
            'uptime': uptime,
            'source_uptime': source_uptime,
            'source_connected': self.source_connection is not None,
            'ws_clients': len(self.ws_clients),
            'unix_clients': len(self.unix_clients),
            'total_clients': len(self.ws_clients) + len(self.unix_clients),
            'messages_from_source': self.metrics['messages_from_source'],
            'messages_to_source': self.metrics['messages_to_source'],
            'bytes_from_source': self.metrics['bytes_from_source'],
            'bytes_to_source': self.metrics['bytes_to_source'],
            'messages_per_minute': messages_per_minute,
            'avg_message_interval': avg_latency,
        }

    async def run(self):
        """Run this source relay"""
        try:
            # Start rebroadcast servers for this source
            await asyncio.gather(
                self.start_websocket_server(),
                self.start_unix_server()
            )

            # Connect to the source
            await self.connect_to_source()

        except asyncio.CancelledError:
            logger.info(f"Source relay cancelled for {self.source_config['url']}")
        except Exception as e:
            logger.error(f"Error in source relay for {self.source_config['url']}: {e}")
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Graceful shutdown"""
        logger.info(f"Shutting down source relay for {self.source_config['url']}...")
        self.running = False

        # Close source connection to break out of receive loop
        if self.source_connection:
            try:
                await self.source_connection.close()
            except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
                pass

        # Close all WebSocket clients
        ws_close_tasks = []
        for client in self.ws_clients.copy():
            ws_close_tasks.append(asyncio.create_task(client.close()))
        if ws_close_tasks:
            await asyncio.gather(*ws_close_tasks, return_exceptions=True)

        # Close all Unix socket clients
        for writer in self.unix_clients.copy():
            try:
                writer.close()
                await writer.wait_closed()
            except (OSError, asyncio.CancelledError):
                pass

        # Close servers
        for server in self.servers:
            server.close()
            await server.wait_closed()

        # Clean up Unix socket files
        socket_path = self.source_config.get('unix_socket_path')
        if socket_path and os.path.exists(socket_path):
            try:
                os.remove(socket_path)
            except OSError:
                pass

        logger.info(f"Shutdown complete for {self.source_config['url']}")


class WebSocketRelay:
    """High-performance WebSocket relay orchestrator"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.source_relays = []
        self.source_tasks = []
        self.running = True
        self.metrics_task = None

    async def run(self):
        """Run the relay service"""
        try:
            sources = self.config.get('sources', [])

            if not sources:
                logger.error("No sources configured!")
                return

            # Validate and create a SourceRelay for each source
            performance_config = self.config.get('performance', {})

            for source_config in sources:
                # Validate that source has at least one endpoint
                if not source_config.get('websocket_port') and not source_config.get('unix_socket_path'):
                    logger.error(f"Source {source_config.get('url', 'unknown')} has no endpoints configured. "
                                f"Please specify at least one of: websocket_port, unix_socket_path")
                    continue

                source_relay = SourceRelay(source_config, performance_config)
                self.source_relays.append(source_relay)
                task = asyncio.create_task(source_relay.run())
                self.source_tasks.append(task)

            # Check if we have any valid sources to run
            if not self.source_tasks:
                logger.error("No valid sources configured. Exiting.")
                return

            # Start metrics display task
            self.metrics_task = asyncio.create_task(self.display_metrics_periodically())

            # Wait for all source relays to complete
            await asyncio.gather(*self.source_tasks)

        except asyncio.CancelledError:
            logger.info("Relay service cancelled")
        except Exception as e:
            logger.error(f"Error in relay service: {e}")
        finally:
            await self.shutdown()

    async def display_metrics_periodically(self):
        """Display metrics for all sources periodically"""
        try:
            while self.running:
                await asyncio.sleep(60)  # Display every 60 seconds

                # Display metrics for all sources
                self.display_metrics()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in metrics display task: {e}")

    def display_metrics(self):
        """Display current metrics for all sources in a visually appealing format"""
        if not self.source_relays:
            return

        # Create separator line
        separator = "=" * 80

        logger.info("")
        logger.info(separator)
        logger.info("📊 VEYLOR METRICS DASHBOARD")
        logger.info(separator)

        for idx, relay in enumerate(self.source_relays, 1):
            metrics = relay.get_metrics_summary()
            source_url = relay.source_config.get('url', 'unknown')

            # Format source header
            print(f"\n🔗 Source #{idx}: {source_url}")
            print("-" * 80)

            # Connection status
            status_icon = "🟢" if metrics['source_connected'] else "🔴"
            status_text = "Connected" if metrics['source_connected'] else "Disconnected"
            print(f"{status_icon} Status: {status_text}")

            # Uptime
            uptime_str = self._format_duration(metrics['uptime'])
            print(f"⏱️  Relay Uptime: {uptime_str}")
            if metrics['source_connected']:
                source_uptime_str = self._format_duration(metrics['source_uptime'])
                print(f"🔌 Source Connected: {source_uptime_str}")

            # Client connections
            print(f"👥 Connected Clients: {metrics['total_clients']} "
                       f"(WebSocket: {metrics['ws_clients']}, Unix: {metrics['unix_clients']})")

            # Message flow - Source to Clients
            print(f"\n📥 Source → Clients:")
            print(f"   Messages: {metrics['messages_from_source']:,}")
            print(f"   Data: {self._format_bytes(metrics['bytes_from_source'])}")
            print(f"   Rate: {metrics['messages_per_minute']} msg/min")

            if metrics['avg_message_interval'] > 0:
                print(f"   Avg Interval: {metrics['avg_message_interval']:.3f}s")

            # Message flow - Clients to Source
            print(f"\n📤 Clients → Source:")
            print(f"   Messages: {metrics['messages_to_source']:,}")
            print(f"   Data: {self._format_bytes(metrics['bytes_to_source'])}")

        print("")
        print(separator)
        print("")
    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"

    def _format_bytes(self, bytes_count: int) -> str:
        """Format byte count in human-readable format"""
        if bytes_count < 1024:
            return f"{bytes_count} B"
        elif bytes_count < 1024 * 1024:
            return f"{bytes_count / 1024:.2f} KB"
        elif bytes_count < 1024 * 1024 * 1024:
            return f"{bytes_count / (1024 * 1024):.2f} MB"
        else:
            return f"{bytes_count / (1024 * 1024 * 1024):.2f} GB"

    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down all source relays...")
        self.running = False

        # Cancel metrics display task
        if self.metrics_task and not self.metrics_task.done():
            self.metrics_task.cancel()

        # First, set all source relays to stop running
        for source_relay in self.source_relays:
            source_relay.running = False
            # Close source connections to break out of receive loops
            if source_relay.source_connection:
                try:
                    await source_relay.source_connection.close()
                except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
                    pass

        # Cancel all running tasks
        for task in self.source_tasks:
            if not task.done():
                task.cancel()

        # Wait for tasks to complete/cancel with their own cleanup
        if self.source_tasks:
            await asyncio.gather(*self.source_tasks, return_exceptions=True)

        logger.info("All source relays shut down")


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file"""
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        sys.exit(1)


async def main(config_path: str, use_tui: bool = False):
    """Main entry point"""
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

    config = load_config(config_path)
    relay = WebSocketRelay(config)

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Received shutdown signal")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    if use_tui and TUI_AVAILABLE:
        # Run with TUI
        app = VeylorTUI(relay_instance=relay)

        # Create TUI log handler
        tui_handler = TUILogHandler(app)
        tui_logging_handler = TUILoggingHandler(tui_handler)

        # Remove console handlers and add TUI handler for veylor logger
        veylor_logger = logging.getLogger('veylor')
        for handler in veylor_logger.handlers[:]:
            veylor_logger.removeHandler(handler)
        veylor_logger.addHandler(tui_logging_handler)

        # Also suppress root logger to prevent stdout output
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            if isinstance(handler, logging.StreamHandler):
                root_logger.removeHandler(handler)

        # Run relay and TUI concurrently
        relay_task = asyncio.create_task(relay.run())

        try:
            await app.run_async()
        except Exception as e:
            logger.error(f"TUI error: {e}")
        finally:
            # Shutdown relay when TUI exits
            relay.running = False
            await relay.shutdown()
            if not relay_task.done():
                relay_task.cancel()
                try:
                    await relay_task
                except asyncio.CancelledError:
                    pass
    elif use_tui and not TUI_AVAILABLE:
        logger.error("TUI mode requested but textual is not installed. Install with: pip install textual")
        sys.exit(1)
    else:
        # Run without TUI (original behavior)
        # Run relay and wait for shutdown signal
        relay_task = asyncio.create_task(relay.run())
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        # Wait for either relay to complete or shutdown signal
        done, pending = await asyncio.wait(
            {relay_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED
    )

    # If shutdown was signaled, trigger shutdown and wait
    if shutdown_event.is_set():
        logger.info("Initiating graceful shutdown...")
        relay.running = False

        # Close all source connections to break receive loops
        for source_relay in relay.source_relays:
            source_relay.running = False
            if source_relay.source_connection:
                try:
                    await source_relay.source_connection.close()
                except Exception:
                    pass

        # Wait for relay to finish shutting down (with timeout)
        if not relay_task.done():
            try:
                await asyncio.wait_for(relay_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Relay shutdown timed out, forcing cancellation")
                relay_task.cancel()
                try:
                    await relay_task
                except asyncio.CancelledError:
                    pass

    # Cancel any remaining tasks
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass



if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Veylor - High-performance WebSocket relay'
    )
    parser.add_argument(
        '-c', '--config',
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--tui',
        action='store_true',
        help='Enable Terminal UI mode'
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    try:
        uvloop.run(main(args.config, use_tui=args.tui))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
