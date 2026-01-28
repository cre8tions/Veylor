# Veylor Project Instructions

## Project Overview
Veylor is a high-performance, non-blocking WebSocket relay/reflector built with Python. It connects to remote WebSocket services and rebroadcasts messages to multiple clients via WebSocket and Unix domain sockets using async I/O. Veylor is production-ready with proper error handling, graceful shutdown, automatic reconnection, and an optional Terminal User Interface (TUI) for real-time monitoring.

### Key Capabilities
- **Non-blocking async I/O**: Built with `asyncio` for maximum throughput and minimal latency
- **Multiple source support**: Connect to multiple remote WebSocket sources simultaneously
- **Per-source endpoints**: Each source can have independent WebSocket ports and/or Unix sockets
- **Bidirectional communication**: Clients can send messages back to the source WebSocket
- **Dual rebroadcast modes**: WebSocket (network) and Unix domain sockets (local IPC)
- **Automatic reconnection**: Configurable reconnection logic with exponential backoff
- **Concurrent message delivery**: Broadcast messages to all clients concurrently
- **Terminal UI (TUI)**: Optional real-time dashboard for monitoring metrics, connections, and logs
- **Proper graceful shutdown**: Clean connection closure and resource cleanup on exit

## Technology Stack
- **Language**: Python 3.7+
- **Event Loop**: `uvloop` (high-performance async event loop)
- **Core Libraries**:
  - `asyncio` for asynchronous I/O
  - `websockets` (>= 12.0) for WebSocket connections
  - `PyYAML` (>= 6.0) for configuration
  - `textual` (>= 0.40.0) for TUI (optional, used when `--tui` flag is passed)
- **Architecture**: Fully asynchronous, non-blocking event loop with `uvloop` for performance

## Coding Standards

### Python Code Style
- Follow PEP 8 style guidelines
- Use type hints where appropriate (from `typing` module)
- Prefer `async`/`await` syntax for all asynchronous operations
- Use descriptive variable names (e.g., `ws_clients`, `unix_clients`)
- Add docstrings for classes and non-trivial methods

### Asynchronous Programming
- Always use `async def` for coroutines
- Use `await` for all I/O operations
- Use `asyncio.create_task()` for concurrent operations
- Use `asyncio.gather()` for waiting on multiple tasks
- Handle `asyncio.CancelledError` for graceful shutdown
- Never use blocking I/O operations

### Error Handling
- Use try/except blocks for error-prone operations
- Log errors using the configured logger
- Always handle client disconnections gracefully
- Use `return_exceptions=True` with `asyncio.gather()` when broadcasting

### Logging
- Use the configured logger (`logging.getLogger('veylor')`)
- Log levels: INFO for connections/disconnections, ERROR for failures, DEBUG for verbose output
- Include contextual information in log messages (e.g., client addresses, URLs)

## Configuration
- Configuration is stored in `config.yaml` (YAML format)
- Use `config.yaml.example` as a template
- Never commit actual credentials or tokens to the repository
- Configuration structure includes:
  - `sources`: List of WebSocket sources to connect to
  - `rebroadcast`: WebSocket and Unix socket server settings
  - `performance`: Queue sizes and reconnection parameters

## Performance Considerations
- Maintain zero-copy message forwarding where possible
- Use concurrent message delivery with `asyncio.gather()`
- Handle backpressure with async queues
- Minimize memory allocations during message broadcast
- Keep the event loop responsive - no blocking operations

## File Organization
- **Main application**: `veylor.py` - Core relay/reflector logic
- **Terminal UI**: `veylor_tui.py` - TUI dashboard using Textual framework
- **Configuration**: `config.yaml` (user-specific, not in repo), `config.yaml.example` (template)
- **Dependencies**: `requirements.txt`
- **Examples**: `examples/` directory with client examples
- **System integration**: `scripts/veylor.service` (systemd service file)
- **Documentation**: `README.md`

## Testing and Running
- **Install dependencies**: `pip install -r requirements.txt`
- **Run application**: `python veylor.py` (uses `config.yaml` by default)
- **Custom config**: `python veylor.py -c /path/to/config.yaml`
- **Verbose logging**: `python veylor.py -v`
- **Terminal UI**: `python veylor.py --tui` (enables real-time monitoring dashboard)
- **Combined**: `python veylor.py -c config.yaml --tui -v` (custom config with TUI and verbose logging)
- **Example clients**: See `examples/` directory for WebSocket and Unix socket client examples

## Signal Handling
- Support graceful shutdown on SIGTERM and SIGINT
- Close all connections properly during shutdown
- Clean up Unix socket files on exit

## Libraries to Use
- **WebSocket**: Use `websockets` library (>= 12.0)
- **YAML**: Use `PyYAML` for configuration parsing
- **Async I/O**: Use built-in `asyncio` module with `uvloop` for high performance
- **Logging**: Use built-in `logging` module
- **TUI**: Use `textual` (>= 0.40.0) for Terminal UI components when implementing TUI features

## Libraries to Avoid
- Avoid synchronous HTTP/WebSocket libraries
- Do not use threading or multiprocessing unless explicitly needed
- Avoid adding heavy dependencies - keep the project lightweight

## Files/Directories to Ignore
- `config.yaml` (contains user-specific configuration)
- `__pycache__/`
- `*.pyc`
- `*.pyo`
- `.vscode/`
- `.idea/`
- `venv/`
- `.env`

## Documentation
- Keep `README.md` updated with feature changes
- Include usage examples for new features
- Document configuration options in `config.yaml.example`
- Add inline comments only when code behavior is non-obvious

## Best Practices
- Make minimal, surgical changes to existing code
- Maintain backward compatibility with existing configurations
- Test WebSocket connections and message broadcasting after changes
- Verify graceful shutdown behavior after modifications
- Check for resource leaks (unclosed connections, tasks)

## TUI Development Guidelines

### Architecture
The Terminal UI (`veylor_tui.py`) is built with the Textual framework and runs alongside the main relay logic:

- **Non-blocking**: TUI runs concurrently with the relay without impacting WebSocket performance
- **Reactive widgets**: Uses Textual's reactive system for real-time metric updates
- **Log aggregation**: Integrates with the logging system to display application logs in real-time

### Key Components

**VeylorTUI (Main Application)**
- Initializes Textual app with layout and widgets
- Manages connection to main relay for metrics
- Handles user input and navigation

**MetricCard Widget**
- Displays individual metrics (connections, messages sent/received, etc.)
- Uses reactive properties for automatic updates
- Custom render methods for formatted output

**ConnectionStatus Widget**
- Shows connection status indicator (🟢 Connected / 🔴 Disconnected)
- Displays current URL and uptime
- Updates reactively as source connection state changes

**SourceMetricsPanel Widget**
- Aggregates metrics for a single WebSocket source
- Displays per-source connection counts and message throughput
- Updates in real-time as metrics change

**ClientList Widget**
- Displays individual connected clients with their addresses
- Organized by connection type: WebSocket vs Unix socket
- Shows client IP:port or Unix socket identifiers
- Updates in real-time as clients connect/disconnect
- Empty state indicates no active clients for that type

### TUI Integration Points

1. **Main Application Integration** (`veylor.py`):
   - TUI is started conditionally when `--tui` flag is passed
   - Main relay shares metrics via a thread-safe queue
   - TUI receives updates asynchronously without blocking relay

2. **Metrics Communication**:
   - Relay publishes metrics to TUI via async queues
   - Metrics include: active connections, messages sent/received, connection status, uptime
   - Client addresses (IP:port for WebSocket, identifiers for Unix sockets) are included
   - Updates are non-blocking and decoupled from relay logic

3. **Logging Integration**:
   - Custom logging handler (`TUILoggingHandler`) routes logs to TUI
   - Log messages appear in real-time on the dashboard
   - Both file and TUI logging run concurrently

### Styling and Layout

- **Color scheme**: Uses Textual's built-in colors (cyan for labels, yellow for values, green for status)
- **Layout**: Horizontal and vertical containers for responsive design
- **Refresh**: Uses Textual's reactive system for automatic UI updates
- **Borders**: Static containers use borders for visual separation

### Performance Considerations

- TUI operations are completely asynchronous
- Metrics updates are queued and batched
- No blocking operations in the relay loop
- Log messages are buffered to prevent UI lag
- Widget renders are optimized for minimal CPU usage

### Development Workflow for TUI Changes

1. Ensure changes use Textual's reactive properties
2. Test TUI responsiveness with high message throughput
3. Verify no blocking calls in the relay
4. Test graceful shutdown from TUI mode
5. Validate that UI updates don't impact relay performance
