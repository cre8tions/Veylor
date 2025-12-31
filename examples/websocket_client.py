#!/usr/bin/env python3
"""
Example WebSocket client to receive messages from Veylor.
"""

import asyncio
import websockets
import argparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('ws_client')


async def receive_messages(url):
    """Connect to Veylor and receive messages"""
    logger.info(f"Connecting to {url}")
    
    try:
        async with websockets.connect(url) as websocket:
            logger.info(f"Connected to {url}")
            
            async for message in websocket:
                logger.info(f"Received: {message}")
                
    except websockets.exceptions.ConnectionClosed:
        logger.info("Connection closed")
    except Exception as e:
        logger.error(f"Error: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='WebSocket client for Veylor')
    parser.add_argument('--url', default='ws://localhost:8765', help='WebSocket URL')
    
    args = parser.parse_args()
    
    try:
        asyncio.run(receive_messages(args.url))
    except KeyboardInterrupt:
        logger.info("Client stopped")
