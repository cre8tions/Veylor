#!/usr/bin/env python3
"""
Example WebSocket client for bidirectional communication with Veylor.
Receives messages from Veylor and can also send messages back to the source.
"""

import asyncio
import websockets
import argparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('ws_bidirectional_client')


async def send_messages(websocket, interval):
    """Send periodic test messages to Veylor"""
    counter = 0
    while True:
        try:
            message = f"Client message {counter}"
            await websocket.send(message)
            logger.info(f"Sent: {message}")
            counter += 1
            await asyncio.sleep(interval)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed while sending")
            break
        except Exception as e:
            logger.error(f"Error sending: {e}")
            break


async def receive_messages(websocket):
    """Receive messages from Veylor"""
    try:
        async for message in websocket:
            logger.info(f"Received: {message}")
    except websockets.exceptions.ConnectionClosed:
        logger.info("Connection closed while receiving")
    except Exception as e:
        logger.error(f"Error receiving: {e}")


async def bidirectional_communication(url, send_interval):
    """Connect to Veylor and handle bidirectional communication"""
    logger.info(f"Connecting to {url}")
    
    try:
        async with websockets.connect(url) as websocket:
            logger.info(f"Connected to {url}")
            
            # Run send and receive concurrently
            await asyncio.gather(
                send_messages(websocket, send_interval),
                receive_messages(websocket)
            )
                
    except Exception as e:
        logger.error(f"Error: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Bidirectional WebSocket client for Veylor')
    parser.add_argument('--url', default='ws://localhost:8765', help='WebSocket URL')
    parser.add_argument('--interval', type=float, default=3.0, 
                        help='Interval between sent messages (seconds)')
    
    args = parser.parse_args()
    
    try:
        asyncio.run(bidirectional_communication(args.url, args.interval))
    except KeyboardInterrupt:
        logger.info("Client stopped")
