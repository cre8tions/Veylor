#!/usr/bin/env python3
"""
Example Unix socket client for bidirectional communication with Veylor.
Receives messages from Veylor and can also send messages back to the source.
"""

import asyncio
import struct
import argparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('unix_bidirectional_client')


async def send_messages(writer, interval):
    """Send periodic test messages to Veylor via Unix socket"""
    counter = 0
    while True:
        try:
            message = f"Unix client message {counter}".encode('utf-8')
            msg_len = len(message)
            
            # Write length prefix (4 bytes, big-endian)
            writer.write(msg_len.to_bytes(4, byteorder='big'))
            writer.write(message)
            await writer.drain()
            
            logger.info(f"Sent: {message.decode('utf-8')}")
            counter += 1
            await asyncio.sleep(interval)
        except Exception as e:
            logger.error(f"Error sending: {e}")
            break


async def receive_messages(reader):
    """Receive messages from Veylor via Unix socket"""
    try:
        while True:
            # Read 4-byte length prefix
            length_data = await reader.read(4)
            if not length_data or len(length_data) < 4:
                logger.info("Connection closed while receiving")
                break
            
            msg_len = struct.unpack('>I', length_data)[0]
            
            # Read message
            message = await reader.read(msg_len)
            if not message:
                break
                
            logger.info(f"Received ({msg_len} bytes): {message.decode('utf-8', errors='replace')}")
    except Exception as e:
        logger.error(f"Error receiving: {e}")


async def bidirectional_communication(socket_path, send_interval):
    """Connect to Veylor Unix socket and handle bidirectional communication"""
    logger.info(f"Connecting to {socket_path}")
    
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        logger.info(f"Connected to {socket_path}")
        
        # Run send and receive concurrently
        await asyncio.gather(
            send_messages(writer, send_interval),
            receive_messages(reader)
        )
            
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Bidirectional Unix socket client for Veylor')
    parser.add_argument('--socket', default='/tmp/veylor.sock', help='Unix socket path')
    parser.add_argument('--interval', type=float, default=3.0, 
                        help='Interval between sent messages (seconds)')
    
    args = parser.parse_args()
    
    try:
        asyncio.run(bidirectional_communication(args.socket, args.interval))
    except KeyboardInterrupt:
        logger.info("Client stopped")
