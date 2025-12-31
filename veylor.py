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
from typing import Set, Optional, Dict, Any
import websockets
from websockets.asyncio.server import serve as ws_serve
from websockets.asyncio.client import connect as ws_connect
import yaml
import argparse


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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

    async def broadcast_message(self, message: bytes):
        """Broadcast message to all connected clients (non-blocking)"""
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
            # Keep connection alive - client will receive broadcasts
            await websocket.wait_closed()
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

        try:
            # Keep connection alive - client will receive broadcasts
            while self.running:
                # Read to detect disconnection
                data = await reader.read(1024)
                if not data:
                    break
                # Echo back or ignore based on protocol
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

        logger.info(f"Starting WebSocket server for source {self.source_config['url']} on {host}:{ws_port}")
        server = await ws_serve(self.handle_websocket_client, host, ws_port)
        self.servers.append(server)
        logger.info(f"WebSocket server started on {host}:{ws_port}")

    async def start_unix_server(self):
        """Start Unix socket rebroadcast server for this source"""
        socket_path = self.source_config.get('unix_socket_path')
        if not socket_path:
            return

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
            except:
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
            except:
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
            except:
                pass

        logger.info(f"Shutdown complete for {self.source_config['url']}")


class WebSocketRelay:
    """High-performance WebSocket relay orchestrator"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.source_relays = []
        self.source_tasks = []
        self.running = True

    async def run(self):
        """Run the relay service"""
        try:
            sources = self.config.get('sources', [])

            if not sources:
                logger.error("No sources configured!")
                return

            # Create a SourceRelay for each source
            performance_config = self.config.get('performance', {})
            
            for source_config in sources:
                source_relay = SourceRelay(source_config, performance_config)
                self.source_relays.append(source_relay)
                task = asyncio.create_task(source_relay.run())
                self.source_tasks.append(task)

            # Wait for all source relays to complete
            await asyncio.gather(*self.source_tasks)

        except asyncio.CancelledError:
            logger.info("Relay service cancelled")
        except Exception as e:
            logger.error(f"Error in relay service: {e}")
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down all source relays...")
        self.running = False

        # First, set all source relays to stop running
        for source_relay in self.source_relays:
            source_relay.running = False
            # Close source connections to break out of receive loops
            if source_relay.source_connection:
                try:
                    await source_relay.source_connection.close()
                except:
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


async def main(config_path: str):
    """Main entry point"""
    config = load_config(config_path)
    relay = WebSocketRelay(config)

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    def signal_handler():
        logger.info("Received shutdown signal")
        relay.running = False

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    await relay.run()


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

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    try:
        asyncio.run(main(args.config))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
