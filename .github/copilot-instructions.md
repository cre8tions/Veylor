# Veylor Project Instructions

## Project Overview
Veylor is a high-performance WebSocket relay/reflector built with Python. It connects to remote WebSocket services and rebroadcasts messages to multiple clients via WebSocket and Unix file sockets using non-blocking async I/O.

## Technology Stack
- **Language**: Python 3.7+
- **Core Libraries**: 
  - `asyncio` for asynchronous I/O
  - `websockets` (>= 12.0) for WebSocket connections
  - `PyYAML` (>= 6.0) for configuration
- **Architecture**: Fully asynchronous, non-blocking event loop

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
- Main application: `veylor.py`
- Configuration example: `config.yaml.example`
- Dependencies: `requirements.txt`
- Examples: `examples/` directory
- Documentation: `README.md`

## Testing and Running
- Install dependencies: `pip install -r requirements.txt`
- Run application: `python veylor.py` (uses `config.yaml` by default)
- Custom config: `python veylor.py -c /path/to/config.yaml`
- Verbose logging: `python veylor.py -v`

## Signal Handling
- Support graceful shutdown on SIGTERM and SIGINT
- Close all connections properly during shutdown
- Clean up Unix socket files on exit

## Libraries to Use
- **WebSocket**: Use `websockets` library (>= 12.0)
- **YAML**: Use `PyYAML` for configuration parsing
- **Async I/O**: Use built-in `asyncio` module
- **Logging**: Use built-in `logging` module

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
