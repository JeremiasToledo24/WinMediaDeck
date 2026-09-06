"""OSD (On-Screen Display) overlay using Tkinter.

Renders a semi-transparent, non-activatable HUD on the monitor
where the cursor is currently positioned. Uses WS_EX_NOACTIVATE
to avoid stealing focus from the active application.

DPI-aware: calls SetProcessDpiAwarenessContext at startup.
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
import queue
import threading
import tkinter as tk
from typing import Optional

from src.models.actions import Action
from src.interfaces.osd import IOSDService
from src.platform.windows.monitors import get_monitor_at_cursor

logger = logging.getLogger(__name__)

# Win32 constants for window styling
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020

user32 = ctypes.WinDLL("user32", use_last_error=True)

user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND

user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long

user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long

# Action display labels and icons
_ACTION_DISPLAY: dict[Action, tuple[str, str]] = {
    Action.VOLUME_DOWN: ("🔉", "Volumen -"),
    Action.VOLUME_UP: ("🔊", "Volumen +"),
    Action.MUTE: ("🔇", "Silencio"),
    Action.PREVIOUS: ("⏮", "Anterior"),
    Action.PLAY_PAUSE: ("⏯", "Play / Pausa"),
    Action.NEXT: ("⏭", "Siguiente"),
    Action.STOP: ("⏹", "Detener"),
    Action.CALCULATOR: ("🧮", "Calculadora"),
    Action.BROWSER: ("🌐", "Navegador"),
    Action.MEDIA_SELECT: ("🎵", "Selector Media"),
    Action.MAIL: ("📧", "Correo"),
    Action.TOGGLE_PAUSE: ("⏸", "Pausa App"),
}

# OSD visual constants (harmonized with landing_v3.html and SettingsWindow)
_OSD_WIDTH = 280
_OSD_HEIGHT = 80
_OSD_BG = "#1b1b18"        # --ink from landing_v3.html
_OSD_FG = "#f2f1ed"        # --panel from landing_v3.html
_OSD_ACCENT = "#4e8f6b"    # --active tint from landing_v3.html
_OSD_ICON_SIZE = 28
_OSD_FONT_FAMILY = "Segoe UI"
_OSD_CORNER_RADIUS = 16
_OSD_PADDING = 20
_OSD_BOTTOM_MARGIN = 60


def _set_dpi_awareness() -> None:
    """Set DPI awareness to Per-Monitor V2 if available."""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        u32 = ctypes.windll.user32
        u32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if not u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            raise OSError("SetProcessDpiAwarenessContext returned False")
        logger.debug("DPI awareness set to Per-Monitor V2")
    except (OSError, AttributeError):
        try:
            # Fallback: SetProcessDpiAwareness(2) = Per-Monitor
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            logger.debug("DPI awareness set to Per-Monitor (fallback)")
        except (OSError, AttributeError):
            logger.debug("DPI awareness APIs not available")


class OSDService(IOSDService):
    """Tkinter-based OSD overlay.

    Runs on its own thread with a Tkinter mainloop. All show/hide
    operations are dispatched via Tkinter's thread-safe after() method.
    """

    def __init__(self, duration_ms: int = 1000, theme: str = "dark"):
        """
        Args:
            duration_ms: How long the OSD remains visible (milliseconds).
            theme: Initial visual theme ('dark' or 'light').
        """
        self._duration_ms = duration_ms
        self._theme = theme.lower()
        self._osd_queue: queue.Queue[Optional[Action]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._root: Optional[tk.Tk] = None
        self._content_frame: Optional[tk.Frame] = None
        self._label_icon: Optional[tk.Label] = None
        self._label_text: Optional[tk.Label] = None
        self._canvas: Optional[tk.Canvas] = None
        self._hide_after_id: Optional[str] = None
        self._started = False
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the OSD thread."""
        if self._started:
            return

        _set_dpi_awareness()

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._osd_main,
            name="WinMediaDeck-OSD",
            daemon=True,
        )
        self._thread.start()
        self._started = True

    def update_theme(self, theme: str) -> None:
        """Update OSD theme dynamically ('dark' or 'light')."""
        self._theme = theme.lower() if theme.lower() in ("light", "dark") else "dark"
        if self._root:
            try:
                self._root.after(0, self._apply_theme)
            except Exception:
                pass

    def _apply_theme(self) -> None:
        """Apply current theme to OSD widgets using landing_v3.html tokens."""
        if not self._root:
            return
        is_light = self._theme == "light"
        bg = "#f2f1ed" if is_light else "#1b1b18"       # --panel vs --ink
        fg = "#1b1b18" if is_light else "#f2f1ed"       # --ink vs --panel
        accent = "#3c6e52" if is_light else "#4e8f6b"   # --active vs bright active
        self._root.configure(bg=bg)
        if self._content_frame:
            self._content_frame.configure(bg=bg)
        if self._label_icon:
            self._label_icon.configure(bg=bg, fg=accent)
        if self._label_text:
            self._label_text.configure(bg=bg, fg=fg)

    def _osd_main(self) -> None:
        """Main function for the OSD thread."""
        try:
            self._root = tk.Tk()
            self._root.withdraw()
            self._root.overrideredirect(True)
            self._root.attributes("-topmost", True)
            self._root.attributes("-alpha", 0.92)

            # Set window style (non-activatable)
            self._root.update_idletasks()
            hwnd = user32.GetParent(self._root.winfo_id())
            if not hwnd:
                hwnd = self._root.winfo_id()

            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ex_style |= WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)

            # Create the OSD layout
            self._content_frame = tk.Frame(self._root, padx=_OSD_PADDING, pady=12)
            self._content_frame.pack(fill="both", expand=True)

            self._label_icon = tk.Label(
                self._content_frame,
                text="",
                font=(_OSD_FONT_FAMILY, _OSD_ICON_SIZE),
                anchor="w",
            )
            self._label_icon.pack(side="left", padx=(0, 12))

            self._label_text = tk.Label(
                self._content_frame,
                text="",
                font=(_OSD_FONT_FAMILY, 14, "bold"),
                anchor="w",
            )
            self._label_text.pack(side="left", fill="x", expand=True)

            # Apply initial theme
            self._apply_theme()

            # Poll the queue periodically
            self._poll_queue()

            # Run mainloop
            self._root.mainloop()

        except Exception:
            logger.exception("OSD thread crashed")
        finally:
            self._started = False

    def _poll_queue(self) -> None:
        """Check for pending OSD display requests."""
        if self._stop_event.is_set():
            if self._root:
                self._root.quit()
            return

        try:
            while True:
                action = self._osd_queue.get_nowait()
                if action is None:
                    # Shutdown signal
                    if self._root:
                        self._root.quit()
                    return
                self._display_action(action)
        except queue.Empty:
            pass

        if self._root:
            self._root.after(50, self._poll_queue)

    def _display_action(self, action: Action) -> None:
        """Display the OSD for the given action."""
        if not self._root or not self._label_icon or not self._label_text:
            return

        # Cancel any pending hide
        if self._hide_after_id:
            self._root.after_cancel(self._hide_after_id)
            self._hide_after_id = None

        # Get display info
        icon, text = _ACTION_DISPLAY.get(action, ("❓", action.value))

        # Update labels
        self._label_icon.configure(text=icon)
        self._label_text.configure(text=text)

        # Position on the monitor with the cursor
        monitor = get_monitor_at_cursor()
        if monitor:
            x = monitor.left + (monitor.width - _OSD_WIDTH) // 2
            y = monitor.top + monitor.height - _OSD_HEIGHT - _OSD_BOTTOM_MARGIN
        else:
            # Fallback: center of primary screen
            sw = self._root.winfo_screenwidth()
            sh = self._root.winfo_screenheight()
            x = (sw - _OSD_WIDTH) // 2
            y = sh - _OSD_HEIGHT - _OSD_BOTTOM_MARGIN

        self._root.geometry(f"{_OSD_WIDTH}x{_OSD_HEIGHT}+{x}+{y}")
        self._root.deiconify()
        self._root.lift()

        # Schedule auto-hide
        self._hide_after_id = self._root.after(
            self._duration_ms, self._hide_osd
        )

    def _hide_osd(self) -> None:
        """Hide the OSD window."""
        self._hide_after_id = None
        if self._root:
            self._root.withdraw()

    def show(self, action: Action) -> None:
        """Queue an OSD display request (thread-safe)."""
        try:
            self._osd_queue.put_nowait(action)
        except queue.Full:
            pass

    def hide(self) -> None:
        """Request immediate OSD hide."""
        if self._root:
            try:
                self._root.after(0, self._hide_osd)
            except Exception:
                pass

    def shutdown(self) -> None:
        """Shut down the OSD subsystem.

        Idempotent: safe to call multiple times.
        """
        if not self._started:
            return

        self._stop_event.set()
        try:
            self._osd_queue.put_nowait(None)  # shutdown signal
        except queue.Full:
            pass

        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

        self._started = False
        logger.info("OSD service stopped")

    def update_duration(self, duration_ms: int) -> None:
        """Update the display duration.

        Args:
            duration_ms: New duration in milliseconds.
        """
        self._duration_ms = duration_ms
