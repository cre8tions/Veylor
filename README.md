# Veylor
High-performance WebSocket relay/reflector

Veylor is a fast, efficient, non-blocking Python application that connects to remote WebSocket services and rebroadcasts messages to multiple clients via WebSocket and Unix file sockets.

## Features

- **Non-blocking async I/O**: Built with `asyncio` for maximum throughput and efficiency
- **Multiple source support**: Connect to multiple remote WebSocket sources
- **Per-source endpoints**: Each source can have its own WebSocket port and/or Unix socket
- **Bidirectional communication**: Clients can send messages back to the source WebSocket
- **Dual rebroadcast modes**:
  - WebSocket server for network clients
  - Unix domain sockets for local IPC
- **Automatic reconnection**: Configurable reconnection logic for source connections
- **Concurrent message delivery**: Messages are broadcast to all clients concurrently
- **Production-ready**: Proper error handling, logging, and graceful shutdown

## Installation

```bash
# Clone the repository
git clone https://github.com/cre8tions/Veylor.git
cd Veylor

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Create a `config.yaml` file based on the provided example:

```bash
cp config.yaml.example config.yaml
```

Edit `config.yaml` to configure your sources and rebroadcast endpoints:

```yaml
sources:
  - url: "wss://example.com/websocket"
    headers:
      Authorization: "Bearer your-token"
    # Rebroadcast on WebSocket port 8765
    websocket_port: 8765
    # Optional: also rebroadcast on Unix socket
    # unix_socket_path: "/tmp/veylor_source1.sock"

  # Another source on a different port
  - url: "wss://api.example.com/feed"
    websocket_port: 8766
    unix_socket_path: "/tmp/veylor_feed.sock"

performance:
  max_queue_size: 1000
  reconnect_delay: 5
  reconnect_max_attempts: 0  # 0 for infinite
```

### Per-Source Configuration

Each source can be configured with:
- `websocket_port`: Local port for WebSocket clients to connect (optional)
- `websocket_host`: Host to bind WebSocket server (default: `0.0.0.0`)
- `unix_socket_path`: Local Unix socket path for IPC clients (optional)

**Note**: Each source must have at least one endpoint configured (`websocket_port` or `unix_socket_path`).

## Usage

### Basic Usage

```bash
# Run with default config.yaml
python veylor.py

# Run with custom config file
python veylor.py -c /path/to/config.yaml

# Run with verbose logging
python veylor.py -v
```

### Connect as a WebSocket Client

```python
import asyncio
import websockets

async def receive_messages():
    async with websockets.connect('ws://localhost:8765') as websocket:
        async for message in websocket:
            print(f"Received: {message}")

asyncio.run(receive_messages())
```

### Connect via Unix Socket

```python
import asyncio
import struct

async def receive_from_unix():
    reader, writer = await asyncio.open_unix_connection('/tmp/veylor.sock')

    while True:
        # Read 4-byte length prefix
        length_data = await reader.read(4)
        if not length_data:
            break

        msg_len = struct.unpack('>I', length_data)[0]

        # Read message
        message = await reader.read(msg_len)
        print(f"Received: {message.decode('utf-8')}")

asyncio.run(receive_from_unix())
```

### Bidirectional Communication

Veylor supports 2-way communication - clients can send messages back to the source WebSocket.

**WebSocket Client (Send & Receive):**

```python
import asyncio
import websockets

async def bidirectional():
    async with websockets.connect('ws://localhost:8765') as websocket:
        # Send a message to the source
        await websocket.send("Hello from client")

        # Receive messages from the source
        async for message in websocket:
            print(f"Received: {message}")

asyncio.run(bidirectional())
```

**Unix Socket Client (Send & Receive):**

```python
import asyncio

async def bidirectional_unix():
    reader, writer = await asyncio.open_unix_connection('/tmp/veylor.sock')

    # Send a message to the source
    message = b"Hello from Unix client"
    msg_len = len(message)
    writer.write(msg_len.to_bytes(4, byteorder='big'))
    writer.write(message)
    await writer.drain()

    # Receive messages from the source
    while True:
        length_data = await reader.read(4)
        if not length_data or len(length_data) < 4:
            break
        msg_len = int.from_bytes(length_data, byteorder='big')
        message = await reader.read(msg_len)
        print(f"Received: {message.decode('utf-8')}")

asyncio.run(bidirectional_unix())
```

See `examples/websocket_bidirectional_client.py` and `examples/unix_socket_bidirectional_client.py` for complete examples.

## Architecture

Veylor uses a fully asynchronous architecture with per-source isolation and bidirectional message flow:

1. **Per-Source Relays**: Each WebSocket source gets its own dedicated relay instance
2. **Independent Endpoints**: Each source can have its own WebSocket port and/or Unix socket
3. **Source Connection**: Establishes WebSocket connection to remote source with auto-reconnect
4. **Bidirectional Message Flow**:
   - **Source → Clients**: Messages from source are broadcast to all connected clients concurrently
   - **Clients → Source**: Messages from clients are forwarded back to the source WebSocket
5. **Concurrent Broadcasting**: Broadcasts messages to all clients of that source concurrently using `asyncio.gather()`
6. **Client Management**: Automatically handles client connections/disconnections per source

### Architecture Benefits

- **Isolation**: Issues with one source don't affect others
- **Flexibility**: Different sources can use different endpoint types
- **Scalability**: Easy to add new sources without affecting existing ones
- **Performance**: Each source has its own broadcast pipeline

### Performance Characteristics

- **Zero-copy message forwarding** where possible
- **Concurrent message delivery** to all clients
- **Non-blocking I/O** throughout the entire pipeline
- **Automatic backpressure handling** via async queues
- **Efficient memory usage** with shared message buffers

## Command Line Options

```
usage: veylor.py [-h] [-c CONFIG] [-v]

Veylor - High-performance WebSocket relay

optional arguments:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
                        Path to configuration file (default: config.yaml)
  -v, --verbose         Enable verbose logging
```

## Signal Handling

Veylor gracefully handles shutdown signals:

- `SIGTERM`: Graceful shutdown
- `SIGINT` (Ctrl+C): Graceful shutdown

On shutdown, Veylor will:
1. Stop accepting new connections
2. Close all client connections gracefully
3. Close source connections
4. Clean up Unix socket files

## Requirements

- Python 3.7+
- websockets >= 12.0
- aiohttp >= 3.9.0
- PyYAML >= 6.0

## Service

Use Ubuntu systemd or similar

```
sudo cp scripts/veylor.serviice /etc/systemd/system

sudo systemctl daemon-reload
sudo systemctl start veylor.service

sudo systemctl enable veylor.service

```

Check status

```
systemctl status myscript.service
# To view live logs:
journalctl -u veylor.service -f
```

## License

See LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Changelog

- 1.0.0
  - Iinitial release
