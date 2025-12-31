#!/usr/bin/env python3
"""
Example WebSocket test server that generates test messages.
This simulates a remote WebSocket source for testing Veylor.
"""

import asyncio
import websockets
from websockets.server import serve
import json
import time
import argparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('test_server')


async def send_test_messages(websocket):
    """Send periodic test messages to connected clients"""
    counter = 0
    try:
        while True:
            # Generate test message
            message = {
                "counter": counter,
                "timestamp": time.time(),
                "message": f"Test message {counter}"
            }
            
            # Send as JSON
            await websocket.send(json.dumps(message))
            logger.debug(f"Sent: {message}")
            
            counter += 1
            await asyncio.sleep(1)  # Send message every second
            
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        logger.error(f"Error sending: {e}")


async def receive_messages(websocket):
    """Receive messages from clients (forwarded from Veylor)"""
    try:
        async for message in websocket:
            logger.info(f"Received from client: {message}")
            
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        logger.error(f"Error receiving: {e}")


async def handle_client(websocket, path):
    """Handle bidirectional communication with connected clients"""
    client_addr = websocket.remote_address
    logger.info(f"Client connected: {client_addr}")
    
    try:
        # Run send and receive concurrently
        # Use return_exceptions=True to handle failures gracefully
        results = await asyncio.gather(
            send_test_messages(websocket),
            receive_messages(websocket),
            return_exceptions=True
        )
        
        # Log any exceptions that occurred
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Task failed: {result}")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        logger.info(f"Client disconnected: {client_addr}")


async def main(host, port):
    """Start test WebSocket server"""
    logger.info(f"Starting test WebSocket server on {host}:{port}")
    async with serve(handle_client, host, port):
        logger.info(f"Test server running on ws://{host}:{port}")
        await asyncio.Future()  # Run forever


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Test WebSocket server for Veylor')
    parser.add_argument('--host', default='localhost', help='Host to bind to')
    parser.add_argument('--port', type=int, default=9999, help='Port to bind to')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    try:
        asyncio.run(main(args.host, args.port))
    except KeyboardInterrupt:
        logger.info("Server stopped")
