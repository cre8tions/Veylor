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
            
            # Read message
            message = await reader.read(msg_len)
            if not message:
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
