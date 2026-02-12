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
    from veylor_tui import VeylorTUI
    TUI_AVAILABLE = True
except ImportError:
    TUI_AVAILABLE = False
    VeylorTUI = None  # type: ignore


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger('veylor')


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

        # Track pending broadcast tasks to prevent memory leaks from fire-and-forget patterns
        self._pending_tasks: Set[asyncio.Task] = set()

        # Metrics tracking
        self.metrics = {
            'messages_from_source': 0,
            'messages_to_source': 0,
            'bytes_from_source': 0,
            'bytes_to_source': 0,
            'message_timestamps': deque(maxlen=35000),  # Keep last 10000 message timestamps for rate calculation
            'start_time': time.time(),
            'last_message_time': None,
            'source_connected_at': None,
            'source_latency': 0.0,  # Connection latency in seconds from websockets module
            # Extended metrics
            'bytes_ts_from': deque(maxlen=5000),  # (timestamp, bytes) for throughput calc
            'bytes_ts_to': deque(maxlen=5000),
            'peak_msg_rate': 0,
            'peak_throughput_in': 0,
            'peak_throughput_out': 0,
            'min_msg_size': 0,  # Will be set on first message
            'max_msg_size': 0,
            'total_msg_size': 0,
            'msg_count_for_avg': 0,  # Separate counter for rolling average calculation
            'error_counts': {
                'connection_errors': 0,
                'send_errors': 0,
                'dropped_messages': 0
            }
        }

    async def broadcast_message(self, message: bytes):
        """Broadcast message to all connected clients (non-blocking)"""
        # Update metrics
        now = time.time()
        msg_len = len(message)

        self.metrics['messages_from_source'] += 1
        self.metrics['bytes_from_source'] += msg_len
        self.metrics['last_message_time'] = now
        self.metrics['message_timestamps'].append(now)

        # Extended metrics updates
        self.metrics['bytes_ts_from'].append((now, msg_len))
        # Update min_msg_size (0 means not yet set)
        if self.metrics['min_msg_size'] == 0 or msg_len < self.metrics['min_msg_size']:
            self.metrics['min_msg_size'] = msg_len
        self.metrics['max_msg_size'] = max(self.metrics['max_msg_size'], msg_len)

        # Use rolling average calculation to prevent unbounded growth
        # Keep a window of last N messages for average calculation
        self.metrics['msg_count_for_avg'] += 1
        # Exponential moving average to prevent unbounded accumulation
        alpha = 0.01  # Smoothing factor for EMA
        if self.metrics['total_msg_size'] == 0:
            self.metrics['total_msg_size'] = msg_len
        else:
            self.metrics['total_msg_size'] = (1 - alpha) * self.metrics['total_msg_size'] + alpha * msg_len

        # Broadcast to WebSocket clients (concurrent, non-blocking)
        if self.ws_clients:
            ws_tasks = []
            for client in self.ws_clients.copy():
                try:
                    ws_tasks.append(asyncio.create_task(client.send(message)))
                except Exception as e:
                    logger.error(f"Error queuing WebSocket message: {e}")
                    self.metrics['error_counts']['send_errors'] += 1
                    self.ws_clients.discard(client)

            # Don't await here - let tasks run concurrently
            # Track task to prevent memory leak from fire-and-forget pattern
            if ws_tasks:
                task = asyncio.create_task(self._wait_ws_sends(ws_tasks))
                self._track_task(task)

        # Broadcast to Unix socket clients (concurrent, non-blocking)
        if self.unix_clients:
            unix_tasks = []
            for writer in self.unix_clients.copy():
                try:
                    # Queue the send/drain as a task to avoid blocking
                    unix_tasks.append(asyncio.create_task(self._send_unix_message(writer, message)))
                except Exception as e:
                    logger.error(f"Error queuing Unix socket message: {e}")
                    self.unix_clients.discard(writer)

            # Don't await here - let tasks run concurrently
            # Track task to prevent memory leak from fire-and-forget pattern
            if unix_tasks:
                task = asyncio.create_task(self._wait_unix_sends(unix_tasks))
                self._track_task(task)

    def _track_task(self, task: asyncio.Task) -> None:
        """Track a fire-and-forget task to prevent memory leaks"""
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _wait_ws_sends(self, tasks):
        """Wait for WebSocket sends to complete"""
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    self.metrics['error_counts']['send_errors'] += 1
                    logger.debug(f"WebSocket send error: {result}")
        except Exception as e:
            logger.debug(f"Error in _wait_ws_sends: {e}")

    async def _wait_unix_sends(self, tasks):
        """Wait for Unix socket sends to complete"""
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass

    async def _send_unix_message(self, writer: asyncio.StreamWriter, message: bytes):
        """Send message to a single Unix socket client"""
        try:
            msg_len = len(message)
            writer.write(msg_len.to_bytes(4, byteorder='big'))
            writer.write(message)
            await writer.drain()
        except Exception as e:
            logger.error(f"Error sending to Unix socket client: {e}")
            self.unix_clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass

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
                        msg_len = len(msg_bytes)
                        self.metrics['messages_to_source'] += 1
                        self.metrics['bytes_to_source'] += msg_len
                        # Extended metrics
                        now = time.time()
                        self.metrics['bytes_ts_to'].append((now, msg_len))

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
                # Use bytearray to avoid O(n²) concatenation for large messages
                buf = bytearray()
                remaining = msg_len
                while remaining > 0:
                    chunk = await reader.read(min(remaining, 8192))
                    if not chunk:
                        break
                    buf.extend(chunk)
                    remaining -= len(chunk)

                # Verify we received complete message
                if len(buf) != msg_len:
                    logger.error(f"Incomplete message from {peer}: expected {msg_len}, got {len(buf)}")
                    break

                # Forward message to source WebSocket
                message = bytes(buf)
                if self.source_connection:
                    try:
                        # Update metrics
                        self.metrics['messages_to_source'] += 1
                        self.metrics['bytes_to_source'] += len(message)
                        # Extended metrics
                        now = time.time()
                        self.metrics['bytes_ts_to'].append((now, len(message)))

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

                    # Send initial ping to measure connection latency
                    # The websocket.latency property is 0 until first ping/pong exchange
                    try:
                        pong_waiter = await websocket.ping()
                        initial_latency = await pong_waiter
                        self.metrics['source_latency'] = initial_latency
                        logger.info(f"Connected to source: {url} (latency: {initial_latency*1000:.2f}ms)")
                    except Exception as e:
                        logger.warning(f"Could not measure initial latency for {url}: {e}")
                        self.metrics['source_latency'] = 0.0
                        logger.info(f"Connected to source: {url}")

                    attempt = 0  # Reset attempt counter on successful connection

                    # Receive and broadcast messages
                    async for message in websocket:
                        if not self.running:
                            break

                        # Update latency from the websocket's built-in keepalive pings
                        # This is updated automatically after each ping/pong exchange
                        if websocket.latency > 0:
                            self.metrics['source_latency'] = websocket.latency

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

    def _get_client_addresses(self) -> tuple:
        """Get lists of client addresses organized by type"""
        ws_addrs = []
        unix_addrs = []

        # Collect WebSocket client addresses
        for client in self.ws_clients:
            try:
                addr = client.remote_address
                if addr:
                    host, port = addr
                    ws_addrs.append(f"{host}:{port}")
            except:
                ws_addrs.append("unknown")

        # Collect Unix socket client addresses
        for writer in self.unix_clients:
            try:
                peername = writer.get_extra_info('peername', 'unknown')
                unix_addrs.append(str(peername))
            except:
                unix_addrs.append("unknown")

        return ws_addrs, unix_addrs

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Calculate current metrics summary"""
        now = time.time()
        uptime = now - self.metrics['start_time']

        # Calculate messages per minute (scan from newest, deque is chronologically ordered)
        cutoff_60 = now - 60
        messages_per_minute = sum(1 for ts in reversed(self.metrics['message_timestamps']) if ts >= cutoff_60)

        # Calculate average message interval without copying the deque
        avg_latency = 0.0
        ts_deque = self.metrics['message_timestamps']
        if len(ts_deque) > 1:
            avg_latency = (ts_deque[-1] - ts_deque[0]) / (len(ts_deque) - 1)

        # Calculate source uptime
        source_uptime = 0.0
        if self.metrics['source_connected_at']:
            source_uptime = now - self.metrics['source_connected_at']

        # Get client addresses
        ws_addrs, unix_addrs = self._get_client_addresses()

        # Calculate throughput (bytes/sec) - last 5 seconds
        throughput_in = 0
        throughput_out = 0
        window = 5.0

        # Ingress throughput (scan from newest to avoid full-copy list comprehension)
        cutoff_tp = now - window
        total_bytes_in = sum(b for t, b in reversed(self.metrics['bytes_ts_from']) if t >= cutoff_tp)
        if total_bytes_in:
            throughput_in = total_bytes_in / window

        # Egress throughput (approximate by multiplying ingress by clients for broadcast + client msgs)
        # For more accuracy, we'd track per-client sends, but this is a good approximation for broadcast
        total_clients = len(self.ws_clients) + len(self.unix_clients)
        throughput_out = throughput_in * total_clients

        # Add client-to-source throughput
        total_bytes_to = sum(b for t, b in reversed(self.metrics['bytes_ts_to']) if t >= cutoff_tp)
        if total_bytes_to:
            client_upload_rate = total_bytes_to / window
            throughput_in += client_upload_rate # Client uploads are ingress to relay
            throughput_out += client_upload_rate # And egress to source

        # Update peaks
        self.metrics['peak_msg_rate'] = max(self.metrics['peak_msg_rate'], messages_per_minute)
        self.metrics['peak_throughput_in'] = max(self.metrics['peak_throughput_in'], throughput_in)
        self.metrics['peak_throughput_out'] = max(self.metrics['peak_throughput_out'], throughput_out)

        # Avg message size (using exponential moving average stored in total_msg_size)
        avg_msg_size = self.metrics['total_msg_size'] if self.metrics['messages_from_source'] > 0 else 0

        return {
            'uptime': uptime,
            'source_uptime': source_uptime,
            'source_connected': self.source_connection is not None,
            'source_latency': self.metrics['source_latency'],
            'ws_clients': len(self.ws_clients),
            'unix_clients': len(self.unix_clients),
            'total_clients': len(self.ws_clients) + len(self.unix_clients),
            'messages_from_source': self.metrics['messages_from_source'],
            'messages_to_source': self.metrics['messages_to_source'],
            'bytes_from_source': self.metrics['bytes_from_source'],
            'bytes_to_source': self.metrics['bytes_to_source'],
            'messages_per_minute': messages_per_minute,
            'avg_message_interval': avg_latency,
            'ws_client_addrs': ws_addrs,
            'unix_client_addrs': unix_addrs,
            # Enhanced metrics
            'throughput_in': throughput_in,
            'throughput_out': throughput_out,
            'peak_msg_rate': self.metrics['peak_msg_rate'],
            'peak_throughput_in': self.metrics['peak_throughput_in'],
            'max_msg_size': self.metrics['max_msg_size'],
            'avg_msg_size': avg_msg_size,
            'errors': dict(self.metrics['error_counts']),
            'pending_tasks': len(self._pending_tasks)  # For debugging task accumulation
        }

    def reset_metrics(self, preserve_peaks: bool = False) -> None:
        """Reset metrics counters to prevent unbounded growth.

        Args:
            preserve_peaks: If True, keep peak values; otherwise reset everything
        """
        now = time.time()

        # Store peaks if we want to preserve them
        old_peaks = {}
        if preserve_peaks:
            old_peaks = {
                'peak_msg_rate': self.metrics['peak_msg_rate'],
                'peak_throughput_in': self.metrics['peak_throughput_in'],
                'peak_throughput_out': self.metrics['peak_throughput_out'],
            }

        # Reset counters
        self.metrics['messages_from_source'] = 0
        self.metrics['messages_to_source'] = 0
        self.metrics['bytes_from_source'] = 0
        self.metrics['bytes_to_source'] = 0
        self.metrics['msg_count_for_avg'] = 0

        # Clear deques
        self.metrics['message_timestamps'].clear()
        self.metrics['bytes_ts_from'].clear()
        self.metrics['bytes_ts_to'].clear()

        # Reset size metrics
        self.metrics['min_msg_size'] = 0
        self.metrics['max_msg_size'] = 0
        self.metrics['total_msg_size'] = 0

        # Reset error counts
        for key in self.metrics['error_counts']:
            self.metrics['error_counts'][key] = 0

        # Reset peaks if not preserving
        if not preserve_peaks:
            self.metrics['peak_msg_rate'] = 0
            self.metrics['peak_throughput_in'] = 0
            self.metrics['peak_throughput_out'] = 0
        else:
            self.metrics.update(old_peaks)

        # Update start time to now for uptime calculation
        self.metrics['start_time'] = now

        logger.info(f"Metrics reset for source {self.source_config.get('url', 'unknown')}")

    def cleanup_stale_data(self, max_age_seconds: float = 120.0) -> int:
        """Remove stale entries from deques older than max_age_seconds.

        This helps prevent memory buildup when the application runs for long periods.
        Returns the number of entries cleaned up.

        Args:
            max_age_seconds: Maximum age of entries to keep (default: 120 seconds)

        Returns:
            Number of entries removed
        """
        now = time.time()
        cutoff = now - max_age_seconds
        cleaned = 0

        # Clean message_timestamps deque
        while self.metrics['message_timestamps'] and self.metrics['message_timestamps'][0] < cutoff:
            self.metrics['message_timestamps'].popleft()
            cleaned += 1

        # Clean bytes_ts_from deque
        while self.metrics['bytes_ts_from'] and self.metrics['bytes_ts_from'][0][0] < cutoff:
            self.metrics['bytes_ts_from'].popleft()
            cleaned += 1

        # Clean bytes_ts_to deque
        while self.metrics['bytes_ts_to'] and self.metrics['bytes_ts_to'][0][0] < cutoff:
            self.metrics['bytes_ts_to'].popleft()
            cleaned += 1

        return cleaned

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

        # Cancel and await all pending broadcast tasks to prevent leaks
        if self._pending_tasks:
            for task in self._pending_tasks.copy():
                if not task.done():
                    task.cancel()
            # Wait for all pending tasks to complete/cancel
            if self._pending_tasks:
                await asyncio.gather(*self._pending_tasks, return_exceptions=True)
            self._pending_tasks.clear()

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

    def __init__(self, config: Dict[str, Any], tui_mode: bool = False):
        self.config = config
        self.source_relays = []
        self.source_tasks = []
        self.running = True
        self.metrics_task = None
        self.cleanup_task = None
        self.tui_mode = tui_mode  # Skip periodic metrics display when TUI is active

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

            # Start cleanup task (runs in both TUI and headless modes)
            self.cleanup_task = asyncio.create_task(self._periodic_cleanup())

            # Start metrics display task only when TUI is not active
            # (TUI has its own real-time metrics display)
            if not self.tui_mode:
                self.metrics_task = asyncio.create_task(self.display_metrics_periodically())

            # Wait for all source relays to complete
            await asyncio.gather(*self.source_tasks)

        except asyncio.CancelledError:
            logger.info("Relay service cancelled")
        except Exception as e:
            logger.error(f"Error in relay service: {e}")
        finally:
            await self.shutdown()

    async def _periodic_cleanup(self):
        """Periodically clean stale metric data to bound memory usage.

        Runs in both TUI and headless modes to ensure deque entries
        don't accumulate beyond the useful window.
        """
        try:
            while self.running:
                await asyncio.sleep(300)  # Every 5 minutes
                total_cleaned = 0
                for source_relay in self.source_relays:
                    total_cleaned += source_relay.cleanup_stale_data(max_age_seconds=120.0)
                if total_cleaned > 0:
                    logger.debug(f"Cleaned up {total_cleaned} stale metric entries")
        except asyncio.CancelledError:
            pass

    async def display_metrics_periodically(self):
        """Display metrics for all sources periodically"""
        try:
            while self.running:
                await asyncio.sleep(60)  # Display every 60 seconds
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
            logger.info(f"\n🔗 Source #{idx}: {source_url}")
            logger.info("-" * 80)

            # Connection status
            status_icon = "🟢" if metrics['source_connected'] else "🔴"
            status_text = "Connected" if metrics['source_connected'] else "Disconnected"
            logger.info(f"{status_icon} Status: {status_text}")

            # Uptime
            uptime_str = self._format_duration(metrics['uptime'])
            logger.info(f"⏱️  Relay Uptime: {uptime_str}")
            if metrics['source_connected']:
                source_uptime_str = self._format_duration(metrics['source_uptime'])
                logger.info(f"🔌 Source Connected: {source_uptime_str}")

            # Client connections
            logger.info(f"👥 Connected Clients: {metrics['total_clients']} "
                       f"(WebSocket: {metrics['ws_clients']}, Unix: {metrics['unix_clients']})")

            # Message flow - Source to Clients
            logger.info(f"\n📥 Source → Clients:")
            logger.info(f"   Messages: {metrics['messages_from_source']:,}")
            logger.info(f"   Data: {self._format_bytes(metrics['bytes_from_source'])}")
            logger.info(f"   Rate: {metrics['messages_per_minute']} msg/min")

            if metrics['avg_message_interval'] > 0:
                logger.info(f"   Avg Interval: {metrics['avg_message_interval']:.3f}s")

            # Message flow - Clients to Source
            logger.info(f"\n📤 Clients → Source:")
            logger.info(f"   Messages: {metrics['messages_to_source']:,}")
            logger.info(f"   Data: {self._format_bytes(metrics['bytes_to_source'])}")

        logger.info("")
        logger.info(separator)
        logger.info("")
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

        # Cancel cleanup task
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()

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
    relay = WebSocketRelay(config, tui_mode=use_tui)

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
        app = VeylorTUI(relay_instance=relay) if VeylorTUI else None

        # Suppress console logging when TUI is active to prevent output corruption
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            if isinstance(handler, logging.StreamHandler):
                root_logger.removeHandler(handler)
        veylor_logger = logging.getLogger('veylor')
        for handler in veylor_logger.handlers[:]:
            veylor_logger.removeHandler(handler)

        # Run relay and TUI concurrently
        relay_task = asyncio.create_task(relay.run())

        try:
            await app.run_async() if app else None
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
