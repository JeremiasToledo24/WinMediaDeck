"""System tray application using pystray.

Provides a system tray icon with visual state indication
(RUNNING/PAUSED/BLOCKED/FAILED) and a context menu for
pause/resume, autostart toggle, and quit.
"""

import logging
import threading
from typing import Callable, Optional
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from src.models.states import AppState

logger = logging.getLogger(__name__)

# Icon dimensions
_ICON_SIZE = 64

# Colors for each state — Exact color tokens from landing_v3.html
_STATE_COLORS: dict[AppState, tuple[str, str]] = {
    # (symbol_fill, tile_accent)
    AppState.RUNNING: ("#ffffff", "#3c6e52"),     # --active (#3c6e52) forest green
    AppState.PAUSED: ("#ffffff", "#9a7b1f"),      # --paused (#9a7b1f) warm amber
    AppState.BLOCKED: ("#ffffff", "#a13d3d"),     # --blocked (#a13d3d) brick red
    AppState.FAILED: ("#ffffff", "#7a7a72"),      # error dot (#7a7a72) slate grey
    AppState.STARTING: ("#ffffff", "#1c5c8a"),    # --link (#1c5c8a) classic blue
    AppState.VALIDATING: ("#ffffff", "#1c5c8a"),  # --link (#1c5c8a) classic blue
    AppState.READY: ("#ffffff", "#1c5c8a"),       # --link (#1c5c8a) classic blue
    AppState.STOPPING: ("#ffffff", "#7a7a72"),    # slate grey
    AppState.STOPPED: ("#ffffff", "#7a7a72"),     # slate grey
}


def _create_icon_image(state: AppState) -> Image.Image:
    """Generate a tray icon image for the given app state.

    Args:
        state: The current AppState.

    Returns:
        A PIL Image suitable for the system tray.
    """
    fill, accent = _STATE_COLORS.get(
        state, ("#9e9e9e", "#616161")
    )

    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw a rounded rectangle background
    margin = 4
    draw.rounded_rectangle(
        [margin, margin, _ICON_SIZE - margin, _ICON_SIZE - margin],
        radius=10,
        fill=accent,
    )

    # Draw a music note / media symbol
    cx, cy = _ICON_SIZE // 2, _ICON_SIZE // 2

    if state == AppState.RUNNING:
        # Play triangle
        draw.polygon(
            [(cx - 8, cy - 12), (cx - 8, cy + 12), (cx + 12, cy)],
            fill=fill,
        )
    elif state == AppState.PAUSED:
        # Pause bars
        bar_w = 6
        gap = 4
        draw.rectangle(
            [cx - gap - bar_w, cy - 10, cx - gap, cy + 10],
            fill=fill,
        )
        draw.rectangle(
            [cx + gap, cy - 10, cx + gap + bar_w, cy + 10],
            fill=fill,
        )
    elif state == AppState.BLOCKED:
        # Warning triangle
        draw.polygon(
            [(cx, cy - 14), (cx - 14, cy + 10), (cx + 14, cy + 10)],
            fill=fill,
        )
        draw.rectangle([cx - 2, cy - 6, cx + 2, cy + 2], fill=accent)
        draw.rectangle([cx - 2, cy + 4, cx + 2, cy + 8], fill=accent)
    elif state == AppState.FAILED:
        # X mark
        draw.line(
            [(cx - 10, cy - 10), (cx + 10, cy + 10)],
            fill=fill, width=4,
        )
        draw.line(
            [(cx + 10, cy - 10), (cx - 10, cy + 10)],
            fill=fill, width=4,
        )
    else:
        # Default: dot
        draw.ellipse(
            [cx - 8, cy - 8, cx + 8, cy + 8],
            fill=fill,
        )

    return img


class TrayApp:
    """System tray application for WinMediaDeck.

    Provides visual state indication and a context menu.
    """

    def __init__(
        self,
        on_toggle_pause: Optional[Callable[[], None]] = None,
        on_toggle_autostart: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
        on_open_config: Optional[Callable[[], None]] = None,
        on_open_settings: Optional[Callable[[], None]] = None,
        on_diagnostic: Optional[Callable[[], None]] = None,
        get_autostart_state: Optional[Callable[[], bool]] = None,
        on_toggle_theme: Optional[Callable[[], None]] = None,
        get_theme_state: Optional[Callable[[], str]] = None,
        on_about: Optional[Callable[[], None]] = None,
    ):
        """
        Args:
            on_toggle_pause: Callback for pause/resume toggle.
            on_toggle_autostart: Callback for autostart toggle.
            on_quit: Callback for quit action.
            on_open_config: Callback to open config file in editor.
            on_open_settings: Callback to open the settings window.
            on_diagnostic: Callback to run diagnostic.
            get_autostart_state: Callable returning current autostart state.
            on_toggle_theme: Callback for theme toggle (dark/light).
            get_theme_state: Callable returning current theme ('dark' or 'light').
            on_about: Callback to open the About dialog.
        """
        self._on_toggle_pause = on_toggle_pause
        self._on_toggle_autostart = on_toggle_autostart
        self._on_quit = on_quit
        self._on_open_config = on_open_config
        self._on_open_settings = on_open_settings
        self._on_diagnostic = on_diagnostic
        self._get_autostart_state = get_autostart_state
        self._on_toggle_theme = on_toggle_theme
        self._get_theme_state = get_theme_state
        self._on_about = on_about

        self._icon = None
        self._thread: Optional[threading.Thread] = None
        self._current_state = AppState.STARTING
        self._started = False

    def start(self, initial_state: AppState = AppState.STARTING) -> None:
        """Start the system tray icon on a background thread.

        Args:
            initial_state: The initial AppState to display.
        """
        if self._started:
            return

        self._current_state = initial_state

        self._thread = threading.Thread(
            target=self._tray_main,
            name="WinMediaDeck-Tray",
            daemon=True,
        )
        self._thread.start()
        self._started = True

    def _tray_main(self) -> None:
        """Main function for the tray thread."""
        try:
            import pystray  # type: ignore[import-untyped]

            image = _create_icon_image(self._current_state)

            menu_items = []

            # Toggle pause
            if self._on_toggle_pause:
                menu_items.append(
                    pystray.MenuItem(
                        lambda item: (
                            "⏸ Pausar" if self._current_state == AppState.RUNNING
                            else "▶ Reanudar"
                        ),
                        self._handle_toggle_pause,
                    )
                )

            menu_items.append(pystray.Menu.SEPARATOR)

            # Settings window
            if self._on_open_settings:
                menu_items.append(
                    pystray.MenuItem("⚙ Ajustes", self._handle_open_settings)
                )

            # Open config
            if self._on_open_config:
                menu_items.append(
                    pystray.MenuItem("📁 Abrir config.json", self._handle_open_config)
                )

            # Toggle autostart
            if self._on_toggle_autostart:
                menu_items.append(
                    pystray.MenuItem(
                        lambda item: (
                            "✓ Inicio automático"
                            if self._get_autostart_state and self._get_autostart_state()
                            else "  Inicio automático"
                        ),
                        self._handle_toggle_autostart,
                    )
                )

            # Toggle theme
            if self._on_toggle_theme:
                menu_items.append(
                    pystray.MenuItem(
                        lambda item: (
                            "☀️ Tema claro"
                            if self._get_theme_state and self._get_theme_state() == "dark"
                            else "🌙 Tema oscuro"
                        ),
                        self._handle_toggle_theme,
                    )
                )

            # Diagnostic
            if self._on_diagnostic:
                menu_items.append(
                    pystray.MenuItem("🔍 Diagnóstico", self._handle_diagnostic)
                )

            # About dialog (al último en la lista de opciones)
            if self._on_about:
                menu_items.append(
                    pystray.MenuItem("ℹ Acerca de", self._handle_about)
                )

            menu_items.append(pystray.Menu.SEPARATOR)

            # Quit
            if self._on_quit:
                menu_items.append(
                    pystray.MenuItem("❌ Salir", self._handle_quit)
                )

            self._icon = pystray.Icon(
                name="WinMediaDeck",
                icon=image,
                title=self._current_state.tray_tooltip,
                menu=pystray.Menu(*menu_items),
            )

            if self._icon is not None:
                self._icon.run()

        except Exception:
            logger.exception("Tray application crashed")
        finally:
            self._started = False

    def _handle_toggle_pause(self, icon, item) -> None:
        if self._on_toggle_pause:
            self._on_toggle_pause()

    def _handle_toggle_autostart(self, icon, item) -> None:
        if self._on_toggle_autostart:
            self._on_toggle_autostart()

    def _handle_toggle_theme(self, icon, item) -> None:
        if self._on_toggle_theme:
            threading.Thread(
                target=self._on_toggle_theme,
                name="WinMediaDeck-ToggleThemeWorker",
                daemon=True,
            ).start()

    def _handle_quit(self, icon, item) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
        if self._on_quit:
            # Execute on_quit in a separate daemon thread to avoid joining/deadlocking the tray thread
            threading.Thread(
                target=self._on_quit,
                name="WinMediaDeck-QuitWorker",
                daemon=True,
            ).start()

    def _handle_open_config(self, icon, item) -> None:
        if self._on_open_config:
            self._on_open_config()

    def _handle_diagnostic(self, icon, item) -> None:
        if self._on_diagnostic:
            self._on_diagnostic()

    def _handle_open_settings(self, icon, item) -> None:
        if self._on_open_settings:
            self._on_open_settings()

    def _handle_about(self, icon=None, item=None) -> None:
        if self._on_about:
            threading.Thread(
                target=self._on_about,
                name="WinMediaDeck-AboutWorker",
                daemon=True,
            ).start()

    def notify(self, title: str, message: str) -> None:
        """Show a native Windows balloon notification.

        Args:
            title: Notification title.
            message: Notification body text.
        """
        if self._icon:
            try:
                self._icon.notify(message, title)
            except Exception:
                logger.exception("Failed to show balloon notification")

    def update_state(self, state: AppState) -> None:
        """Update the tray icon to reflect a new app state.

        Args:
            state: The new AppState.
        """
        self._current_state = state
        if self._icon:
            try:
                self._icon.icon = _create_icon_image(state)
                self._icon.title = state.tray_tooltip
            except Exception:
                logger.exception("Failed to update tray icon")

    def shutdown(self) -> None:
        """Stop the tray icon.

        Idempotent: safe to call multiple times.
        """
        if not self._started:
            return

        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

        # Never join the current thread (raises RuntimeError and deadlocks)
        if self._thread and threading.current_thread() != self._thread:
            try:
                self._thread.join(timeout=3.0)
            except Exception:
                pass
        self._thread = None

        self._started = False
        logger.info("Tray application stopped")
