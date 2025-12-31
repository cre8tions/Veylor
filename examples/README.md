# Veylor Examples

This directory contains example scripts for testing and demonstrating Veylor.

## Test Server

`test_server.py` - A WebSocket server that generates test messages every second.

```bash
# Start the test server
python examples/test_server.py

# Or with custom host/port
python examples/test_server.py --host 0.0.0.0 --port 9999
```

## WebSocket Client

`websocket_client.py` - Connects to Veylor via WebSocket and prints received messages.

```bash
# Connect to Veylor's WebSocket server
python examples/websocket_client.py

# Or with custom URL
python examples/websocket_client.py --url ws://localhost:8765
```

## Unix Socket Client

`unix_socket_client.py` - Connects to Veylor via Unix socket and prints received messages.

```bash
# Connect to Veylor's Unix socket
python examples/unix_socket_client.py

# Or with custom socket path
python examples/unix_socket_client.py --socket /tmp/veylor.sock
```

## Full Test Workflow

To test Veylor end-to-end:

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
