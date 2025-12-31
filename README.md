# Veylor
High-performance WebSocket relay/reflector

Veylor is a fast, efficient, non-blocking Python application that connects to remote WebSocket services and rebroadcasts messages to multiple clients via WebSocket and Unix file sockets.

## Features

- **Non-blocking async I/O**: Built with `asyncio` for maximum throughput and efficiency
- **Multiple source support**: Connect to multiple remote WebSocket sources
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

rebroadcast:
  websocket:
    enabled: true
    host: "0.0.0.0"
    port: 8765
  
  unix_socket:
    enabled: true
    path: "/tmp/veylor.sock"

performance:
  max_queue_size: 1000
  reconnect_delay: 5
  reconnect_max_attempts: 0  # 0 for infinite
```

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

## Architecture

Veylor uses a fully asynchronous architecture for maximum performance:

1. **Source Connection**: Establishes WebSocket connection(s) to remote sources
2. **Message Reception**: Receives messages from source(s) in non-blocking manner
3. **Concurrent Broadcasting**: Broadcasts messages to all connected clients concurrently using `asyncio.gather()`
4. **Client Management**: Automatically handles client connections/disconnections

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

## License

See LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
