# Veylor Examples

This directory contains example scripts for testing and demonstrating Veylor.

## Test Server

`test_server.py` - A WebSocket server that generates test messages every second and receives messages from clients (bidirectional).

```bash
# Start the test server
python examples/test_server.py

# Or with custom host/port
python examples/test_server.py --host 0.0.0.0 --port 9999

# With verbose logging
python examples/test_server.py -v
```

## WebSocket Client

`websocket_client.py` - Connects to Veylor via WebSocket and prints received messages (receive-only).

```bash
# Connect to Veylor's WebSocket server
python examples/websocket_client.py

# Or with custom URL
python examples/websocket_client.py --url ws://localhost:8765
```

## Unix Socket Client

`unix_socket_client.py` - Connects to Veylor via Unix socket and prints received messages (receive-only).

```bash
# Connect to Veylor's Unix socket
python examples/unix_socket_client.py

# Or with custom socket path
python examples/unix_socket_client.py --socket /tmp/veylor.sock
```

## Bidirectional WebSocket Client

`websocket_bidirectional_client.py` - Connects to Veylor via WebSocket, receives messages, and sends periodic messages back to the source.

```bash
# Connect and send messages every 3 seconds (default)
python examples/websocket_bidirectional_client.py

# Or with custom URL and interval
python examples/websocket_bidirectional_client.py --url ws://localhost:8765 --interval 5
```

## Bidirectional Unix Socket Client

`unix_socket_bidirectional_client.py` - Connects to Veylor via Unix socket, receives messages, and sends periodic messages back to the source.

```bash
# Connect and send messages every 3 seconds (default)
python examples/unix_socket_bidirectional_client.py

# Or with custom socket path and interval
python examples/unix_socket_bidirectional_client.py --socket /tmp/veylor.sock --interval 5
```

## Full Test Workflow

### Basic Relay Test (Receive-Only)

To test Veylor's basic relay functionality:

1. **Terminal 1** - Start the test server:
   ```bash
   python examples/test_server.py
   ```

2. **Terminal 2** - Start Veylor:
   ```bash
   python veylor.py
   ```

3. **Terminal 3** - Connect a WebSocket client:
   ```bash
   python examples/websocket_client.py
   ```

4. **Terminal 4** - Connect a Unix socket client:
   ```bash
   python examples/unix_socket_client.py
   ```

You should see test messages flowing from the test server through Veylor to both clients concurrently.

### Bidirectional Communication Test

To test Veylor's 2-way communication:

1. **Terminal 1** - Start the test server with verbose logging:
   ```bash
   python examples/test_server.py -v
   ```

2. **Terminal 2** - Start Veylor with verbose logging:
   ```bash
   python veylor.py -v
   ```

3. **Terminal 3** - Connect a bidirectional WebSocket client:
   ```bash
   python examples/websocket_bidirectional_client.py
   ```

4. **Terminal 4** - Connect a bidirectional Unix socket client:
   ```bash
   python examples/unix_socket_bidirectional_client.py
   ```

You should see:
- Test messages from the server flowing to both clients
- Client messages being forwarded back to the test server
- Logs showing the bidirectional message flow
