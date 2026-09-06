"""Application state machine.

AppState governs the runtime behaviour of the keyboard hook:
- RUNNING: F-keys are intercepted and remapped.
- PAUSED: Hook is installed but all keys pass through (CallNextHookEx).
- FAILED / BLOCKED / STOPPED: Terminal or informational states.
"""

from enum import Enum, unique


@unique
class AppState(Enum):
    """Runtime state of the WinMediaDeck application."""

    STARTING = "starting"
    VALIDATING = "validating"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    BLOCKED = "blocked"
    FAILED = "failed"
    STOPPING = "stopping"
    STOPPED = "stopped"

    @property
    def is_active(self) -> bool:
        """True if the app is in a state where it should process events."""
        return self in (AppState.RUNNING,)

    @property
    def is_alive(self) -> bool:
        """True if the app is in a non-terminal state."""
        return self not in (AppState.FAILED, AppState.STOPPED)

    @property
    def tray_tooltip(self) -> str:
        """Human-readable tooltip for the system tray icon."""
        tooltips = {
            AppState.RUNNING: "WinMediaDeck — activo",
            AppState.PAUSED: "WinMediaDeck — en pausa",
            AppState.BLOCKED: "Entrada bloqueada por una ventana elevada",
            AppState.FAILED: "Error: revisa --diagnostic",
            AppState.STARTING: "WinMediaDeck — iniciando...",
            AppState.VALIDATING: "WinMediaDeck — validando...",
            AppState.READY: "WinMediaDeck — listo",
            AppState.STOPPING: "WinMediaDeck — deteniendo...",
            AppState.STOPPED: "WinMediaDeck — detenido",
        }
        return tooltips.get(self, "WinMediaDeck")
