#!/usr/bin/env python3
"""
Example Unix socket client to receive messages from Veylor.
"""

import asyncio
import struct
import argparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('unix_client')


async def receive_from_unix(socket_path):
    """Connect to Veylor Unix socket and receive messages"""
    logger.info(f"Connecting to {socket_path}")
    
    # Maximum message size (10 MB)
    MAX_MESSAGE_SIZE = 10 * 1024 * 1024
    
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        logger.info(f"Connected to {socket_path}")
        
        while True:
            # Read 4-byte length prefix
            length_data = await reader.read(4)
            if not length_data or len(length_data) < 4:
                logger.info("Connection closed")
                break
            
            msg_len = struct.unpack('>I', length_data)[0]
            
            # Validate message length
            if msg_len <= 0 or msg_len > MAX_MESSAGE_SIZE:
                logger.error(f"Invalid message length: {msg_len}")
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
                logger.error(f"Incomplete message: expected {msg_len}, got {len(message)}")
                break
                
            logger.info(f"Received ({msg_len} bytes): {message.decode('utf-8', errors='replace')}")
            
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Unix socket client for Veylor')
    parser.add_argument('--socket', default='/tmp/veylor.sock', help='Unix socket path')
    
    args = parser.parse_args()
    
    try:
        asyncio.run(receive_from_unix(args.socket))
    except KeyboardInterrupt:
        logger.info("Client stopped")
