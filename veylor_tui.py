#!/usr/bin/env python3
"""
Veylor TUI - Terminal User Interface for Veylor WebSocket Relay

Provides an attractive, real-time dashboard for monitoring relay metrics,
connections, and logs without impacting WebSocket processing performance.
"""

import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Log
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual import events


class MetricCard(Static):
    """A card widget for displaying a single metric"""
    
    value = reactive("")
    label = reactive("")
    
    def __init__(self, label: str, value: str = "0", **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.value = value
    
    def render(self) -> str:
        return f"[bold cyan]{self.label}[/]\n[yellow]{self.value}[/]"


class ConnectionStatus(Static):
    """Widget for displaying connection status"""
    
    status = reactive("🔴 Disconnected")
    url = reactive("")
    uptime = reactive("0s")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def render(self) -> str:
        return f"""[bold]Connection Status[/]
{self.status}
[dim]URL:[/] {self.url}
[dim]Uptime:[/] {self.uptime}"""


class SourceMetricsPanel(Static):
    """Panel displaying metrics for a single source"""
    
    def __init__(self, source_idx: int, **kwargs):
        super().__init__(**kwargs)
        self.source_idx = source_idx
        self.border_title = f"Source #{source_idx}"
        self.border_subtitle = ""
    
    def compose(self) -> ComposeResult:
        with Horizontal(classes="metrics-row"):
            yield ConnectionStatus(id=f"conn-status-{self.source_idx}")
            yield MetricCard("Total Clients", "0", id=f"clients-{self.source_idx}")
            yield MetricCard("WS Clients", "0", id=f"ws-clients-{self.source_idx}")
            yield MetricCard("Unix Clients", "0", id=f"unix-clients-{self.source_idx}")
        
        with Horizontal(classes="metrics-row"):
            yield MetricCard("Messages from Source", "0", id=f"msg-from-{self.source_idx}")
            yield MetricCard("Messages to Source", "0", id=f"msg-to-{self.source_idx}")
            yield MetricCard("Data from Source", "0 B", id=f"data-from-{self.source_idx}")
            yield MetricCard("Data to Source", "0 B", id=f"data-to-{self.source_idx}")
        
        with Horizontal(classes="metrics-row"):
            yield MetricCard("Messages/min", "0", id=f"msg-rate-{self.source_idx}")
            yield MetricCard("Avg Interval", "0.000s", id=f"avg-interval-{self.source_idx}")


class VeylorTUI(App):
    """Veylor Terminal User Interface Application"""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    Header {
        background: $primary;
        color: $text;
    }
    
    Footer {
        background: $primary-darken-2;
    }
    
    #metrics-container {
        height: auto;
        padding: 1;
    }
    
    .metrics-row {
        height: auto;
        margin-bottom: 1;
    }
    
    MetricCard {
        border: solid $primary;
        padding: 1;
        margin-right: 1;
        height: auto;
        min-width: 20;
    }
    
    ConnectionStatus {
        border: solid $success;
        padding: 1;
        margin-right: 1;
        height: auto;
        min-width: 30;
    }
    
    SourceMetricsPanel {
        border: double $accent;
        padding: 1;
        margin-bottom: 1;
        height: auto;
    }
    
    #log-container {
        height: 15;
        border: thick $warning;
        margin-top: 1;
    }
    
    Log {
        background: $surface-darken-1;
    }
    """
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("d", "toggle_dark", "Toggle Dark Mode"),
        ("c", "clear_logs", "Clear Logs"),
    ]
    
    def __init__(self, relay_instance=None, **kwargs):
        super().__init__(**kwargs)
        self.relay_instance = relay_instance
        self.update_task = None
        
    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header(show_clock=True)
        
        with Container(id="metrics-container"):
            # Source panels will be added dynamically
            pass
        
        with Container(id="log-container"):
            yield Log(id="log-viewer", auto_scroll=True)
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Called when app is mounted."""
        self.title = "Veylor WebSocket Relay Dashboard"
        self.sub_title = "High-Performance Message Broadcasting"
        
        # Initialize source panels if relay instance is available
        if self.relay_instance:
            self._initialize_source_panels()
        
        # Start periodic update task
        self.update_task = self.set_interval(0.5, self._update_metrics)
        
        # Display welcome message
        log_widget = self.query_one("#log-viewer", Log)
        log_widget.write_line("[bold green]Veylor TUI started[/]")
        log_widget.write_line("[dim]Press 'q' to quit, 'c' to clear logs, 'd' to toggle dark mode[/]")
    
    def _initialize_source_panels(self) -> None:
        """Initialize metric panels for each source"""
        container = self.query_one("#metrics-container")
        
        for idx, source_relay in enumerate(self.relay_instance.source_relays, 1):
            panel = SourceMetricsPanel(idx)
            container.mount(panel)
    
    def _update_metrics(self) -> None:
        """Update metrics display from relay instance"""
        if not self.relay_instance:
            return
        
        for idx, source_relay in enumerate(self.relay_instance.source_relays, 1):
            metrics = source_relay.get_metrics_summary()
            source_url = source_relay.source_config.get('url', 'unknown')
            
            # Update connection status
            try:
                conn_status = self.query_one(f"#conn-status-{idx}", ConnectionStatus)
                if metrics['source_connected']:
                    conn_status.status = "🟢 Connected"
                else:
                    conn_status.status = "🔴 Disconnected"
                conn_status.url = source_url[:40] + "..." if len(source_url) > 40 else source_url
                conn_status.uptime = self._format_duration(metrics['source_uptime']) if metrics['source_connected'] else "N/A"
            except Exception:
                pass
            
            # Update metric cards
            try:
                self.query_one(f"#clients-{idx}", MetricCard).value = str(metrics['total_clients'])
                self.query_one(f"#ws-clients-{idx}", MetricCard).value = str(metrics['ws_clients'])
                self.query_one(f"#unix-clients-{idx}", MetricCard).value = str(metrics['unix_clients'])
                self.query_one(f"#msg-from-{idx}", MetricCard).value = f"{metrics['messages_from_source']:,}"
                self.query_one(f"#msg-to-{idx}", MetricCard).value = f"{metrics['messages_to_source']:,}"
                self.query_one(f"#data-from-{idx}", MetricCard).value = self._format_bytes(metrics['bytes_from_source'])
                self.query_one(f"#data-to-{idx}", MetricCard).value = self._format_bytes(metrics['bytes_to_source'])
                self.query_one(f"#msg-rate-{idx}", MetricCard).value = str(metrics['messages_per_minute'])
                self.query_one(f"#avg-interval-{idx}", MetricCard).value = f"{metrics['avg_message_interval']:.3f}s"
            except Exception:
                pass
    
    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"
    
    def _format_bytes(self, bytes_count: int) -> str:
        """Format byte count in human-readable format"""
        if bytes_count < 1024:
            return f"{bytes_count} B"
        elif bytes_count < 1024 * 1024:
            return f"{bytes_count / 1024:.2f} KB"
        elif bytes_count < 1024 * 1024 * 1024:
            return f"{bytes_count / (1024 * 1024):.2f} MB"
        else:
            return f"{bytes_count / (1024 * 1024 * 1024):.2f} GB"
    
    def action_toggle_dark(self) -> None:
        """Toggle dark mode."""
        self.dark = not self.dark
    
    def action_clear_logs(self) -> None:
        """Clear the log viewer."""
        log_widget = self.query_one("#log-viewer", Log)
        log_widget.clear()
        log_widget.write_line("[dim]Logs cleared[/]")
    
    def write_log(self, message: str, level: str = "INFO") -> None:
        """Write a log message to the log viewer"""
        try:
            log_widget = self.query_one("#log-viewer", Log)
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            # Color code by level
            if level == "ERROR":
                color = "red"
            elif level == "WARNING":
                color = "yellow"
            elif level == "DEBUG":
                color = "dim"
            else:
                color = "white"
            
            formatted_msg = f"[dim]{timestamp}[/] [{color}]{level:8}[/] {message}"
            log_widget.write_line(formatted_msg)
        except Exception:
            # Silently ignore if TUI is not ready yet
            pass
    
    def on_unmount(self) -> None:
        """Called when app is unmounted."""
        if self.update_task:
            self.update_task.stop()


class TUILogHandler:
    """Log handler that routes logs to the TUI"""
    
    def __init__(self, tui_app: VeylorTUI):
        self.tui_app = tui_app
    
    def write(self, message: str, level: str = "INFO"):
        """Write a log message to the TUI"""
        if self.tui_app:
            self.tui_app.write_log(message, level)
    
    def flush(self):
        """Flush is a no-op for TUI"""
        pass
