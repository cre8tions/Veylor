#!/usr/bin/env python3
"""
Veylor TUI - Terminal User Interface for Veylor WebSocket Relay

Provides an attractive, real-time dashboard for monitoring relay metrics
and connections without impacting WebSocket processing performance.
"""

from typing import Dict, List, Optional, Tuple

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static
from textual.containers import Container, Horizontal
from textual.reactive import reactive


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
        return f"""{self.status}
[dim]URL:[/] {self.url}
[dim]Up:[/] {self.uptime}"""


class SourceMetricsPanel(Static):
    """Panel displaying metrics for a single source"""

    def __init__(self, source_idx: int, **kwargs):
        super().__init__(**kwargs)
        self.source_idx = source_idx
        self.border_title = f"Source #{source_idx}"
        self.border_subtitle = ""

    def compose(self) -> ComposeResult:
        # Compact vertical layout for each source
        yield ConnectionStatus(id=f"conn-status-{self.source_idx}")

        yield Horizontal(
            MetricCard("Clients", "0", id=f"clients-{self.source_idx}"),
            MetricCard("WS", "0", id=f"ws-clients-{self.source_idx}"),
            MetricCard("Unix", "0", id=f"unix-clients-{self.source_idx}"),
            MetricCard("Latency", "0ms", id=f"latency-{self.source_idx}"),
            classes="compact-row"
        )

        yield Horizontal(
            MetricCard("Msg In", "0", id=f"msg-from-{self.source_idx}"),
            MetricCard("Msg Out", "0", id=f"msg-to-{self.source_idx}"),
            classes="compact-row"
        )

        yield Horizontal(
            MetricCard("Data In", "0 B", id=f"data-from-{self.source_idx}"),
            MetricCard("Data Out", "0 B", id=f"data-to-{self.source_idx}"),
            classes="compact-row"
        )

        yield Horizontal(
            MetricCard("Msg/s", "0", id=f"msg-rate-{self.source_idx}"),
            MetricCard("Interval", "0.000s", id=f"avg-interval-{self.source_idx}"),
            MetricCard("Peak/s", "0", id=f"peak-rate-{self.source_idx}"),
            classes="compact-row"
        )

        yield Horizontal(
            MetricCard("In Rate", "0 B/s", id=f"in-rate-{self.source_idx}"),
            MetricCard("Out Rate", "0 B/s", id=f"out-rate-{self.source_idx}"),
            MetricCard("Peak In", "0 B/s", id=f"peak-in-{self.source_idx}"),
            classes="compact-row"
        )

        yield Horizontal(
            MetricCard("Avg Size", "0 B", id=f"avg-size-{self.source_idx}"),
            MetricCard("Max Size", "0 B", id=f"max-size-{self.source_idx}"),
            MetricCard("Errors", "0", id=f"errors-{self.source_idx}"),
            classes="compact-row"
        )

        # Client list widget
        yield ClientList(self.source_idx, id=f"client-list-{self.source_idx}")


class ClientList(Static):
    """Widget displaying connected clients for a source.

    Includes change detection to avoid unnecessary string rebuilds
    and reduce memory allocation churn.
    """

    def __init__(self, source_idx: int, **kwargs):
        super().__init__(**kwargs)
        self.source_idx = source_idx
        self.border_title = f"Connected Clients"
        self._content = ""
        # Track last state to detect changes and avoid unnecessary rebuilds
        self._last_ws_tuple: Tuple[str, ...] = ()
        self._last_unix_tuple: Tuple[str, ...] = ()
        self._refresh_content()  # Initialize content

    def update_clients(self, ws_clients: int, unix_clients: int,
                      ws_addrs: Optional[List[str]] = None, unix_addrs: Optional[List[str]] = None) -> None:
        """Update the client list display.

        Only refreshes if the client list has actually changed to reduce
        memory allocations and CPU usage.
        """
        new_ws = tuple(ws_addrs) if ws_addrs is not None else ()
        new_unix = tuple(unix_addrs) if unix_addrs is not None else ()

        # Only update if data has changed
        if new_ws == self._last_ws_tuple and new_unix == self._last_unix_tuple:
            return  # No changes, skip update

        self._last_ws_tuple = new_ws
        self._last_unix_tuple = new_unix
        self._refresh_content()
        self.refresh()  # Force widget redraw

    def _refresh_content(self) -> None:
        """Rebuild the client list content"""
        lines = []

        ws_clients = self._last_ws_tuple
        unix_clients = self._last_unix_tuple

        # WebSocket clients
        lines.append(f"[bold cyan]WebSocket Clients ({len(ws_clients)}):[/]")
        if ws_clients:
            for addr in ws_clients:
                lines.append(f"  🔌 {addr}")
        else:
            lines.append("  [dim](none)[/]")

        lines.append("")

        # Unix socket clients
        lines.append(f"[bold cyan]Unix Socket Clients ({len(unix_clients)}):[/]")
        if unix_clients:
            for addr in unix_clients:
                lines.append(f"  🔌 {addr}")
        else:
            lines.append("  [dim](none)[/]")

        self._content = "\n".join(lines)

    def render(self) -> str:
        return self._content


class VeylorTUI(App):
    """Veylor Terminal User Interface Application"""

    CSS = """
    Screen {
        background: $surface;
        layout: vertical;
    }

    Header {
        background: $primary;
        color: $text;
        height: auto;
    }

    Footer {
        background: $primary-darken-2;
        height: auto;
    }

    #metrics-container {
        height: auto;
        /* max-height: 60vh; */
        overflow-y: auto;
        padding: 0 1;
    }

    #sources-grid {
        layout: grid;
        grid-size: 3;
        grid-gutter: 1;
        padding: 1 0;
    }

    .compact-row {
        height: 5;
        width: 100%;
        layout: horizontal;
    }

    MetricCard {
        border: solid $primary;
        padding: 0 1;
        margin-right: 1;
        height: 4;
        width: 1fr;
    }

    ConnectionStatus {
        border: solid $success;
        padding: 0 1;
        height: 5;
        width: 100%;
        margin-bottom: 1;
        tint: white 15%;
    }

    ClientList {
        border: solid $accent;
        padding: 1;
        height: auto;
        /* max-height: 12; */
        margin-top: 1;
        overflow-y: auto;
        background: $surface-darken-1;
    }

    .error-highlight {
        background: red;
        color: white;
    }

    SourceMetricsPanel {
        border: panel $accent;
        padding: 1;
        height: auto;
        layout: vertical;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("d", "toggle_dark", "Toggle Dark Mode"),
    ]

    def __init__(self, relay_instance=None, **kwargs):
        super().__init__(**kwargs)
        self.relay_instance = relay_instance
        self.update_task = None
        self._source_widgets: Dict[int, Dict] = {}  # Cached widget references per source

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header(show_clock=True)

        with Container(id="metrics-container"):
            with Container(id="sources-grid"):
                # Source panels will be added dynamically in a grid
                pass

        yield Footer()

    def on_mount(self) -> None:
        """Called when app is mounted."""
        self.title = "Veylor WebSocket Relay Dashboard"
        self.sub_title = "High-Performance Message Broadcasting"

        # Initialize source panels if relay instance is available
        if self.relay_instance:
            self._initialize_source_panels()

        # Start periodic update task
        self.update_task = self.set_interval(1, self._update_metrics)

    def _initialize_source_panels(self) -> None:
        """Initialize metric panels for each source"""
        if not self.relay_instance:
            return

        container = self.query_one("#sources-grid")

        for idx, source_relay in enumerate(self.relay_instance.source_relays, 1):
            panel = SourceMetricsPanel(idx)
            container.mount(panel)

    def _get_source_widgets(self, idx: int) -> Dict:
        """Get cached widget references for a source, populating on first call."""
        widgets = self._source_widgets.get(idx)
        if widgets is not None:
            return widgets
        widgets = {
            'conn_status': self.query_one(f"#conn-status-{idx}", ConnectionStatus),
            'clients': self.query_one(f"#clients-{idx}", MetricCard),
            'ws_clients': self.query_one(f"#ws-clients-{idx}", MetricCard),
            'unix_clients': self.query_one(f"#unix-clients-{idx}", MetricCard),
            'latency': self.query_one(f"#latency-{idx}", MetricCard),
            'msg_from': self.query_one(f"#msg-from-{idx}", MetricCard),
            'msg_to': self.query_one(f"#msg-to-{idx}", MetricCard),
            'data_from': self.query_one(f"#data-from-{idx}", MetricCard),
            'data_to': self.query_one(f"#data-to-{idx}", MetricCard),
            'msg_rate': self.query_one(f"#msg-rate-{idx}", MetricCard),
            'avg_interval': self.query_one(f"#avg-interval-{idx}", MetricCard),
            'peak_rate': self.query_one(f"#peak-rate-{idx}", MetricCard),
            'in_rate': self.query_one(f"#in-rate-{idx}", MetricCard),
            'out_rate': self.query_one(f"#out-rate-{idx}", MetricCard),
            'peak_in': self.query_one(f"#peak-in-{idx}", MetricCard),
            'avg_size': self.query_one(f"#avg-size-{idx}", MetricCard),
            'max_size': self.query_one(f"#max-size-{idx}", MetricCard),
            'errors': self.query_one(f"#errors-{idx}", MetricCard),
            'client_list': self.query_one(f"#client-list-{idx}", ClientList),
        }
        self._source_widgets[idx] = widgets
        return widgets

    def _update_metrics(self) -> None:
        """Update metrics display from relay instance"""
        if not self.relay_instance:
            return

        for idx, source_relay in enumerate(self.relay_instance.source_relays, 1):
            metrics = source_relay.get_metrics_summary()
            source_url = source_relay.source_config.get('url', 'unknown')

            try:
                w = self._get_source_widgets(idx)
            except LookupError:
                continue  # Widgets not yet mounted

            # Update connection status
            try:
                conn_status = w['conn_status']
                if metrics['source_connected']:
                    conn_status.status = "🟢 Connected"
                else:
                    conn_status.status = "🔴 Disconnected"
                conn_status.url = source_url[:40] + "..." if len(source_url) > 40 else source_url
                conn_status.uptime = self._format_duration(metrics['source_uptime']) if metrics['source_connected'] else "N/A"
            except AttributeError:
                pass

            # Update metric cards
            try:
                w['clients'].value = str(metrics['total_clients'])
                w['ws_clients'].value = str(metrics['ws_clients'])
                w['unix_clients'].value = str(metrics['unix_clients'])
                latency_ms = metrics.get('source_latency', 0) * 1000
                w['latency'].value = f"{latency_ms:.2f}ms"
                w['msg_from'].value = f"{metrics['messages_from_source']:,}"
                w['msg_to'].value = f"{metrics['messages_to_source']:,}"
                w['data_from'].value = self._format_bytes(metrics['bytes_from_source'])
                w['data_to'].value = self._format_bytes(metrics['bytes_to_source'])
                w['msg_rate'].value = f"{metrics['messages_per_second']:.1f}"
                w['avg_interval'].value = f"{metrics['avg_message_interval']:.3f}s"

                # Extended metrics
                w['peak_rate'].value = f"{metrics.get('peak_msg_rate_per_sec', 0):.1f}"
                w['in_rate'].value = self._format_bytes(int(metrics.get('throughput_in', 0))) + "/s"
                w['out_rate'].value = self._format_bytes(int(metrics.get('throughput_out', 0))) + "/s"
                w['peak_in'].value = self._format_bytes(int(metrics.get('peak_throughput_in', 0))) + "/s"
                w['avg_size'].value = self._format_bytes(int(metrics.get('avg_msg_size', 0)))
                w['max_size'].value = self._format_bytes(int(metrics.get('max_msg_size', 0)))

                errors = metrics.get('errors', {})
                total_errors = sum(errors.values()) if errors else 0
                error_card = w['errors']
                error_card.value = str(total_errors)
                error_card.set_class(total_errors > 0, "error-highlight")
            except AttributeError:
                pass

            # Update client list with addresses
            try:
                ws_addrs = metrics.get('ws_client_addrs', [])
                unix_addrs = metrics.get('unix_client_addrs', [])
                w['client_list'].update_clients(
                    metrics['ws_clients'],
                    metrics['unix_clients'],
                    ws_addrs,
                    unix_addrs
                )
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
        self.theme = "textual-light" if self.theme == "textual-dark" else "textual-dark"

    def on_unmount(self) -> None:
        """Called when app is unmounted."""
        if self.update_task:
            self.update_task.stop()
            self.update_task = None
        self._source_widgets.clear()
        self.relay_instance = None
