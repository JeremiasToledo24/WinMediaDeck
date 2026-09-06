"""Settings window for hotkey configuration.

Provides a modern, harmonized GUI consistent with the system tray,
OSD visual theme, and the landing_v3.html design system. Configures
F1-F12 hotkey mappings (in a 2-column deck grid), OSD notifications,
visual theme selection (dark/light), and Windows autostart toggles.
"""

import json
import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
from pathlib import Path
from typing import Optional

from PIL import ImageTk

from src import __version__
from src.models.actions import Action
from src.models.events import HOTKEY_VK_MAP
from src.models.states import AppState
from src.config.settings import (
    get_config_path,
    load_config,
    write_config_atomic,
    _default_config_dict,
    SCHEMA_VERSION,
)
from src.core.autostart import AutostartManager
from src.ui.tray_app import _create_icon_image

logger = logging.getLogger(__name__)

# Exact design tokens from landing_v3.html
THEMES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#ffffff",            # --bg from landing_v3.html
        "card_bg": "#f2f1ed",       # --panel from landing_v3.html
        "card_border": "#d7d4c9",   # --line from landing_v3.html
        "border_strong": "#b6b2a3", # --line-strong from landing_v3.html
        "bg_field": "#ffffff",      # crisp white field inside --panel
        "bg_hover": "#e6e3d8",      # hover state on panel
        "fg": "#1b1b18",            # --ink from landing_v3.html
        "fg_dim": "#55534c",        # --ink-soft from landing_v3.html
        "accent": "#3c6e52",        # --active (forest green) from landing_v3.html
        "accent_hover": "#335e46",  # .btn-download:hover from landing_v3.html
        "link": "#1c5c8a",          # --link from landing_v3.html
        "success": "#3c6e52",       # --active from landing_v3.html
        "warning": "#9a7b1f",       # --paused from landing_v3.html
        "danger": "#a13d3d",        # --blocked from landing_v3.html
        "status_bg": "#e2ede6",     # soft active tint on light
    },
    "dark": {
        "bg": "#1b1b18",            # --ink (topstrip & logo base) from landing_v3.html
        "card_bg": "#252522",       # warm dark panel harmonized with --ink
        "card_border": "#3a3933",   # subtle line on dark
        "border_strong": "#525048", # strong line on dark
        "bg_field": "#1c1c1a",      # pre code block background from landing_v3.html
        "bg_hover": "#30302b",      # field hover
        "fg": "#f2f1ed",            # --panel as light primary text
        "fg_dim": "#9c998e",        # muted warm sand text
        "accent": "#4e8f6b",        # accessible bright tint of --active
        "accent_hover": "#5fa57e",  # accent hover
        "link": "#4a9cd6",          # link blue on dark
        "success": "#4e8f6b",       # --active tint
        "warning": "#c9a02a",       # --paused tint
        "danger": "#c94f4f",        # --blocked tint
        "status_bg": "#14261c",     # deep green tint of --active
    },
}

_BG = THEMES["dark"]["bg"]
_CARD_BG = THEMES["dark"]["card_bg"]
_CARD_BORDER = THEMES["dark"]["card_border"]
_BG_FIELD = THEMES["dark"]["bg_field"]
_BG_HOVER = THEMES["dark"]["bg_hover"]
_FG = THEMES["dark"]["fg"]
_FG_DIM = THEMES["dark"]["fg_dim"]
_ACCENT = THEMES["dark"]["accent"]
_ACCENT_HOVER = THEMES["dark"]["accent_hover"]
_SUCCESS = THEMES["dark"]["success"]
_DANGER = THEMES["dark"]["danger"]

_FONT = ("Segoe UI", 10)
_FONT_BOLD = ("Segoe UI", 10, "bold")
_FONT_HEADING = ("Segoe UI", 11, "bold")
_FONT_TITLE = ("Segoe UI", 14, "bold")
_FONT_SMALL = ("Segoe UI", 9)
_FONT_BADGE = ("Segoe UI", 8, "bold")
_FONT_MONO = ("Consolas", 10, "bold")

# Action display names with emojis (harmonized with Tray and OSD)
_ACTION_LABELS: dict[str, str] = {
    "volume_down": "🔉 Volumen -",
    "volume_up": "🔊 Volumen +",
    "mute": "🔇 Silencio",
    "previous": "⏮ Anterior",
    "play_pause": "⏯ Play / Pausa",
    "next": "⏭ Siguiente",
    "stop": "⏹ Detener",
    "calculator": "🧮 Calculadora",
    "browser": "🌐 Navegador",
    "media_select": "🎵 Selector Media",
    "mail": "📧 Correo",
    "toggle_pause": "⏸ Pausa App",
}

# Reverse lookup supporting both emoji-prefixed and plain labels
_LABEL_TO_ACTION: dict[str, str] = {}
for k, v in _ACTION_LABELS.items():
    _LABEL_TO_ACTION[v] = k
    if " " in v:
        _LABEL_TO_ACTION[v.split(" ", 1)[1]] = k

# Sentinel
_UNASSIGNED = "(Sin asignar)"

# All F-keys in order
_FKEYS = [f"F{i}" for i in range(1, 13)]


class SettingsWindow:
    """Tkinter settings window for WinMediaDeck configuration."""

    _instance: Optional["SettingsWindow"] = None
    _about_instance: Optional[tk.Misc] = None
    _lock = threading.Lock()

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or get_config_path()
        self._root: Optional[tk.Tk] = None
        self._icon_photo: Optional[ImageTk.PhotoImage] = None
        self._hotkey_vars: dict[str, tk.StringVar] = {}
        self._combos: dict[str, ttk.Combobox] = {}
        self._osd_enabled_var: Optional[tk.BooleanVar] = None
        self._osd_duration_var: Optional[tk.IntVar] = None
        self._theme_var: Optional[tk.StringVar] = None
        self._current_theme: str = "dark"
        self._themed_widgets: list[tuple[tk.Widget, str]] = []
        self._app_enabled_var: Optional[tk.BooleanVar] = None
        self._autostart_var: Optional[tk.BooleanVar] = None
        self._autostart_manager = AutostartManager()

    @classmethod
    def open(cls, config_path: Optional[Path] = None) -> None:
        """Open the settings window (singleton — only one instance at a time)."""
        with cls._lock:
            if cls._instance is not None and cls._instance._root is not None:
                try:
                    cls._instance._reload_from_disk()
                    cls._instance._root.deiconify()
                    cls._instance._root.lift()
                    cls._instance._root.focus_force()
                    return
                except Exception:
                    cls._instance = None

            instance = cls(config_path)
            cls._instance = instance

        t = threading.Thread(
            target=instance._build_and_run,
            name="WinMediaDeck-Settings",
            daemon=True,
        )
        t.start()

    @classmethod
    def close(cls) -> None:
        """Safely close any active settings window and about dialog."""
        with cls._lock:
            inst = cls._instance
            cls._instance = None
        if inst and inst._root:
            try:
                inst._root.after(0, inst._on_close)
            except Exception:
                pass
        if cls._about_instance:
            try:
                cls._about_instance.destroy()
            except Exception:
                pass
            cls._about_instance = None

    def _open_about(self) -> None:
        """Open discrete About dialog from instance."""
        self.show_about(parent=self._root, theme_name=self._current_theme)

    @classmethod
    def show_about(cls, parent: Optional[tk.Misc] = None, theme_name: Optional[str] = None) -> None:
        """Display the discrete About dialog.

        Args:
            parent: Optional parent Tk/Toplevel window.
            theme_name: Visual theme ('dark' or 'light'). If None, loads from config.
        """
        # If already open, bring to front
        if cls._about_instance is not None:
            try:
                if cls._about_instance.winfo_exists():
                    cls._about_instance.deiconify()
                    cls._about_instance.lift()
                    cls._about_instance.focus_force()
                    return
            except Exception:
                cls._about_instance = None

        if not theme_name:
            if cls._instance and cls._instance._current_theme:
                theme_name = cls._instance._current_theme
            else:
                try:
                    with open(get_config_path(), "r", encoding="utf-8") as f:
                        theme_name = json.load(f).get("theme", "dark")
                except Exception:
                    theme_name = "dark"

        p = THEMES.get(theme_name, THEMES["dark"])

        active_root = None
        if parent and hasattr(parent, "winfo_exists") and parent.winfo_exists() and parent.winfo_viewable():
            active_root = parent
        elif cls._instance and cls._instance._root and cls._instance._root.winfo_exists() and cls._instance._root.winfo_viewable():
            active_root = cls._instance._root

        if active_root:
            try:
                active_root.after(0, lambda: cls._build_about_dialog(active_root, p, is_standalone=False))
                return
            except Exception:
                pass

        # Standalone invocation (e.g. from Tray when SettingsWindow is closed)
        def _runner():
            try:
                dlg = cls._build_about_dialog(None, p, is_standalone=True)
                dlg.mainloop()
            except Exception:
                logger.exception("Failed to show about dialog")

        threading.Thread(target=_runner, name="WinMediaDeck-About", daemon=True).start()

    @classmethod
    def _build_about_dialog(
        cls,
        parent: Optional[tk.Misc],
        p: dict[str, str],
        is_standalone: bool = False,
    ) -> tk.Tk | tk.Toplevel:
        """Build and display the discrete About modal dialog."""
        if is_standalone or parent is None:
            dlg = tk.Tk()
        else:
            dlg = tk.Toplevel(parent)

        cls._about_instance = dlg

        dlg.title("Acerca de WinMediaDeck")
        dlg.configure(bg=p["card_bg"])
        dlg.resizable(False, False)

        try:
            icon_img = _create_icon_image(AppState.RUNNING)
            photo = ImageTk.PhotoImage(icon_img)
            dlg.iconphoto(False, photo)
            dlg._photo_ref = photo  # keep reference
        except Exception:
            pass

        win_w, win_h = 440, 290
        screen_w = dlg.winfo_screenwidth()
        screen_h = dlg.winfo_screenheight()
        if parent and hasattr(parent, "winfo_x") and hasattr(parent, "winfo_y") and parent.winfo_viewable():
            x = parent.winfo_x() + (parent.winfo_width() - win_w) // 2
            y = parent.winfo_y() + (parent.winfo_height() - win_h) // 2
        else:
            x = (screen_w - win_w) // 2
            y = (screen_h - win_h) // 2
        dlg.geometry(f"{win_w}x{win_h}+{x}+{y}")

        dlg.attributes("-topmost", True)
        if not (is_standalone or parent is None):
            try:
                dlg.transient(parent)
                dlg.grab_set()
            except Exception:
                pass

        dlg.deiconify()
        dlg.lift()
        dlg.focus_force()

        content = tk.Frame(dlg, bg=p["card_bg"], padx=20, pady=16)
        content.pack(fill="both", expand=True)

        # Header row: logo + app title
        head_row = tk.Frame(content, bg=p["card_bg"])
        head_row.pack(fill="x", pady=(0, 10))

        # Brand logo square matching landing_v3.html .logo
        logo_box = tk.Frame(head_row, bg=p["fg"], width=28, height=28)
        logo_box.pack(side="left", padx=(0, 12))
        logo_box.pack_propagate(False)
        inner_sq = tk.Frame(logo_box, bg=p["accent"], width=14, height=14)
        inner_sq.place(relx=0.5, rely=0.5, anchor="center")

        title_frame = tk.Frame(head_row, bg=p["card_bg"])
        title_frame.pack(side="left")

        tk.Label(
            title_frame,
            text=f"WinMediaDeck  v{__version__}",
            font=_FONT_TITLE,
            bg=p["card_bg"],
            fg=p["fg"],
        ).pack(anchor="w")

        tk.Label(
            title_frame,
            text="F1–F12, de vuelta al trabajo.",
            font=_FONT_SMALL,
            bg=p["card_bg"],
            fg=p["accent"],
        ).pack(anchor="w")

        # Divider line
        tk.Frame(content, bg=p["card_border"], height=1).pack(fill="x", pady=(0, 10))

        # Description
        tk.Label(
            content,
            text="Controlador de medios y atajos del sistema para Windows.\nEjecución ligera, local y sin servicios en segundo plano.",
            font=_FONT_SMALL,
            bg=p["card_bg"],
            fg=p["fg_dim"],
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # Author info
        author_row = tk.Frame(content, bg=p["card_bg"])
        author_row.pack(fill="x", pady=(0, 4))

        tk.Label(
            author_row,
            text="Desarrollado por:",
            font=_FONT,
            bg=p["card_bg"],
            fg=p["fg_dim"],
        ).pack(side="left", padx=(0, 6))

        tk.Label(
            author_row,
            text="Jeremías Toledo",
            font=_FONT_BOLD,
            bg=p["card_bg"],
            fg=p["fg"],
        ).pack(side="left")

        # Clickable repository link
        link_url = "https://github.com/JeremiasToledo24/WinMediaDeck"
        link_lbl = tk.Label(
            content,
            text="🔗 github.com/JeremiasToledo24/WinMediaDeck",
            font=_FONT_SMALL,
            bg=p["card_bg"],
            fg=p["link"],
            cursor="hand2",
        )
        link_lbl.pack(anchor="w", pady=(0, 8))
        link_lbl.bind("<Button-1>", lambda e: webbrowser.open(link_url))

        # Note / license
        tk.Label(
            content,
            text="Licencia MIT · 100% privado y sin telemetría.",
            font=("Segoe UI", 8),
            bg=p["card_bg"],
            fg=p["fg_dim"],
        ).pack(anchor="w", pady=(0, 12))

        # Close button
        def _close():
            cls._about_instance = None
            try:
                if not (is_standalone or parent is None):
                    dlg.grab_release()
            except Exception:
                pass
            try:
                dlg.quit()
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass

        dlg.protocol("WM_DELETE_WINDOW", _close)

        btn_bar = tk.Frame(content, bg=p["card_bg"])
        btn_bar.pack(fill="x")

        tk.Button(
            btn_bar,
            text="Cerrar",
            font=_FONT,
            bg=p["bg_field"],
            fg=p["fg"],
            activebackground=p["bg_hover"],
            activeforeground=p["fg"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=p["card_border"],
            cursor="hand2",
            padx=20,
            pady=4,
            command=_close,
        ).pack(side="right")

        dlg.focus_set()
        return dlg

    def _reg(self, widget: tk.Widget, role: str) -> tk.Widget:
        """Register a widget for dynamic theme updates."""
        self._themed_widgets.append((widget, role))
        return widget

    def _reload_from_disk(self) -> None:
        """Reload and refresh UI fields with current config on disk and registry."""
        config = self._load_config_dict()
        hotkeys_data = config.get("hotkeys", {})

        for fkey in _FKEYS:
            current_action = hotkeys_data.get(fkey, "")
            current_label = _ACTION_LABELS.get(current_action, _UNASSIGNED)
            if fkey in self._hotkey_vars:
                self._hotkey_vars[fkey].set(current_label)
            if fkey in self._combos:
                self._combos[fkey].set(current_label)

        osd_data = config.get("osd", {})
        if self._osd_enabled_var:
            self._osd_enabled_var.set(osd_data.get("enabled", True))
        if self._osd_duration_var:
            self._osd_duration_var.set(osd_data.get("duration_ms", 1000))

        theme_data = config.get("theme", "dark")
        theme_label = "☀️ Claro" if theme_data == "light" else "🌙 Oscuro"
        if self._theme_var:
            self._theme_var.set(theme_label)
        self._apply_theme(theme_data)

        if self._app_enabled_var:
            self._app_enabled_var.set(config.get("enabled", True))

        if self._autostart_var:
            self._autostart_var.set(self._autostart_manager.is_enabled())

    def _build_and_run(self) -> None:
        """Build the window and enter mainloop."""
        try:
            self._root = tk.Tk()
            self._root.title("WinMediaDeck — Ajustes")
            self._root.resizable(False, False)
            self._root.protocol("WM_DELETE_WINDOW", self._on_close)

            # Set harmonized tray icon on window and taskbar
            try:
                icon_img = _create_icon_image(AppState.RUNNING)
                self._icon_photo = ImageTk.PhotoImage(icon_img)
                self._root.iconphoto(False, self._icon_photo)
            except Exception:
                pass

            # Window dimensions: 2-column layout allows a compact, elegant height
            win_w, win_h = 680, 600
            screen_w = self._root.winfo_screenwidth()
            screen_h = self._root.winfo_screenheight()
            x = (screen_w - win_w) // 2
            y = (screen_h - win_h) // 2
            self._root.geometry(f"{win_w}x{win_h}+{x}+{y}")

            # Load current config
            config_dict = self._load_config_dict()
            initial_theme = config_dict.get("theme", "dark")
            if initial_theme not in THEMES:
                initial_theme = "dark"
            self._current_theme = initial_theme

            # Configure ttk styles
            self._configure_styles(initial_theme)

            # Build UI
            self._build_ui(config_dict)

            # Apply initial theme to all widgets
            self._apply_theme(initial_theme)

            self._root.mainloop()
        except Exception:
            logger.exception("Settings window crashed")
        finally:
            with self._lock:
                SettingsWindow._instance = None

    def _configure_styles(self, theme_name: str = "dark") -> None:
        """Configure ttk widget styles using landing_v3.html design tokens."""
        p = THEMES.get(theme_name, THEMES["dark"])
        style = ttk.Style(self._root)
        style.theme_use("clam")

        # Combobox
        style.configure(
            "Dark.TCombobox",
            fieldbackground=p["bg_field"],
            background=p["bg_field"],
            foreground=p["fg"],
            arrowcolor=p["accent"],
            bordercolor=p["card_border"],
            lightcolor=p["card_border"],
            darkcolor=p["card_border"],
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", p["bg_field"]), ("focus", p["bg_hover"])],
            foreground=[("readonly", p["fg"])],
            selectbackground=[("readonly", p["bg_field"])],
            selectforeground=[("readonly", p["fg"])],
            bordercolor=[("focus", p["accent"])],
        )

        # Checkbutton
        style.configure(
            "Dark.TCheckbutton",
            background=p["card_bg"],
            foreground=p["fg"],
            font=_FONT,
            focuscolor=p["card_bg"],
        )
        style.map(
            "Dark.TCheckbutton",
            background=[("active", p["card_bg"])],
            foreground=[("active", p["fg"])],
        )

        # Scale
        style.configure(
            "Dark.Horizontal.TScale",
            background=p["card_bg"],
            troughcolor=p["card_border"],
            sliderthickness=14,
        )

    def _apply_theme(self, theme_name: str) -> None:
        """Apply theme to all registered widgets and window."""
        theme_name = theme_name.lower() if theme_name.lower() in THEMES else "dark"
        self._current_theme = theme_name
        p = THEMES[theme_name]

        if not self._root:
            return

        self._root.configure(bg=p["bg"])
        self._configure_styles(theme_name)

        for widget, role in self._themed_widgets:
            try:
                if role == "bg_frame":
                    widget.configure(bg=p["bg"])
                elif role == "card_frame":
                    widget.configure(
                        bg=p["card_bg"],
                        highlightbackground=p["card_border"],
                        highlightcolor=p["card_border"],
                    )
                elif role == "header_title":
                    widget.configure(bg=p["bg"], fg=p["fg"])
                elif role == "header_subtitle":
                    widget.configure(bg=p["bg"], fg=p["fg_dim"])
                elif role == "status_frame":
                    widget.configure(
                        bg=p["status_bg"],
                        highlightbackground=p["accent"],
                        highlightcolor=p["accent"],
                    )
                elif role == "status_label":
                    widget.configure(bg=p["status_bg"], fg=p["accent"])
                elif role == "card_header":
                    widget.configure(bg=p["card_bg"], fg=p["accent"])
                elif role == "card_label":
                    widget.configure(bg=p["card_bg"], fg=p["fg"])
                elif role == "dim_label":
                    widget.configure(bg=p["card_bg"], fg=p["fg_dim"])
                elif role == "badge_label":
                    widget.configure(
                        bg=p["bg_field"],
                        fg=p["accent"],
                        highlightbackground=p["card_border"],
                        highlightcolor=p["card_border"],
                    )
                elif role == "accent_value_label":
                    widget.configure(bg=p["card_bg"], fg=p["accent"])
                elif role == "clear_btn":
                    widget.configure(
                        bg=p["bg_field"],
                        fg=p["danger"],
                        activebackground=p["bg_hover"],
                        activeforeground=p["danger"],
                        highlightbackground=p["card_border"],
                        highlightcolor=p["card_border"],
                    )
                elif role == "field_btn":
                    widget.configure(
                        bg=p["bg_field"],
                        fg=p["fg_dim"],
                        activebackground=p["bg_hover"],
                        activeforeground=p["fg"],
                        highlightbackground=p["card_border"],
                        highlightcolor=p["card_border"],
                    )
                elif role == "cancel_btn":
                    widget.configure(
                        bg=p["bg_field"],
                        fg=p["fg"],
                        activebackground=p["bg_hover"],
                        activeforeground=p["fg"],
                        highlightbackground=p["card_border"],
                        highlightcolor=p["card_border"],
                    )
                elif role == "save_btn":
                    widget.configure(
                        bg=p["accent"],
                        fg="#ffffff",
                        activebackground=p["accent_hover"],
                        activeforeground="#ffffff",
                    )
            except Exception:
                pass

    def _load_config_dict(self) -> dict:
        """Load config.json as a raw dictionary."""
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return _default_config_dict()

    def _build_ui(self, config: dict) -> None:
        """Build the complete settings UI."""
        root = self._root
        if not root:
            return

        self._themed_widgets.clear()

        container = self._reg(tk.Frame(root, bg=_BG, padx=20, pady=16), "bg_frame")
        container.pack(fill="both", expand=True)

        # --- Header bar ---
        header = self._reg(tk.Frame(container, bg=_BG), "bg_frame")
        header.pack(fill="x", pady=(0, 14))

        title_box = self._reg(tk.Frame(header, bg=_BG), "bg_frame")
        title_box.pack(side="left")

        self._reg(tk.Label(
            title_box,
            text="WinMediaDeck",
            font=_FONT_TITLE,
            bg=_BG,
            fg=_FG,
        ), "header_title").pack(anchor="w")

        self._reg(tk.Label(
            title_box,
            text="F1–F12, de vuelta al trabajo · Control de medios",
            font=_FONT_SMALL,
            bg=_BG,
            fg=_FG_DIM,
        ), "header_subtitle").pack(anchor="w")

        # Running status badge (matching tray indicator & landing_v3.html statuslegend)
        status_frame = self._reg(tk.Frame(
            header,
            bg=THEMES["dark"]["status_bg"],
            padx=10,
            pady=4,
            highlightthickness=1,
            highlightbackground=THEMES["dark"]["accent"],
        ), "status_frame")
        status_frame.pack(side="right")
        self._reg(tk.Label(
            status_frame,
            text="● ACTIVO EN BANDEJA",
            font=_FONT_BADGE,
            bg=THEMES["dark"]["status_bg"],
            fg=THEMES["dark"]["accent"],
        ), "status_label").pack()

        # --- Hotkeys section (2-column deck grid) ---
        self._build_hotkeys_section(container, config)

        # Bottom row: OSD + General side-by-side
        options_row = self._reg(tk.Frame(container, bg=_BG), "bg_frame")
        options_row.pack(fill="x", pady=(10, 0))

        # --- OSD section ---
        self._build_osd_section(options_row, config)

        # --- General section ---
        self._build_general_section(options_row, config)

        # --- Action Buttons ---
        self._build_buttons(container)

    def _build_hotkeys_section(self, parent: tk.Frame, config: dict) -> None:
        """Build the 2-column deck grid for F1-F12 hotkeys."""
        card = self._reg(tk.Frame(
            parent,
            bg=_CARD_BG,
            highlightthickness=1,
            highlightbackground=_CARD_BORDER,
            padx=14,
            pady=10,
        ), "card_frame")
        card.pack(fill="x")

        # Header with icon
        self._reg(tk.Label(
            card,
            text="⌨  Mapeo de Teclas (F1 — F12)",
            font=_FONT_HEADING,
            bg=_CARD_BG,
            fg=_ACCENT,
        ), "card_header").pack(anchor="w", pady=(0, 8))

        hotkeys_data = config.get("hotkeys", {})
        action_labels = [_UNASSIGNED] + sorted(_ACTION_LABELS.values())

        grid_frame = self._reg(tk.Frame(card, bg=_CARD_BG), "card_frame")
        grid_frame.pack(fill="x")

        # Two columns: F1-F6 on left, F7-F12 on right
        col1 = self._reg(tk.Frame(grid_frame, bg=_CARD_BG), "card_frame")
        col1.pack(side="left", fill="x", expand=True, padx=(0, 10))

        col2 = self._reg(tk.Frame(grid_frame, bg=_CARD_BG), "card_frame")
        col2.pack(side="left", fill="x", expand=True, padx=(10, 0))

        for i, fkey in enumerate(_FKEYS):
            target_col = col1 if i < 6 else col2
            row_frame = self._reg(tk.Frame(target_col, bg=_CARD_BG), "card_frame")
            row_frame.pack(fill="x", pady=2)

            # Key badge (styled like landing_v3.html code tags)
            key_label = self._reg(tk.Label(
                row_frame,
                text=fkey,
                font=_FONT_MONO,
                bg=_BG_FIELD,
                fg=_ACCENT,
                width=4,
                padx=4,
                pady=2,
                highlightthickness=1,
                highlightbackground=_CARD_BORDER,
            ), "badge_label")
            key_label.pack(side="left", padx=(0, 6))

            # Arrow
            self._reg(tk.Label(
                row_frame,
                text="→",
                font=_FONT,
                bg=_CARD_BG,
                fg=_FG_DIM,
            ), "dim_label").pack(side="left", padx=(0, 6))

            # Current action
            current_action = hotkeys_data.get(fkey, "")
            current_label = _ACTION_LABELS.get(current_action, _UNASSIGNED)

            var = tk.StringVar(master=self._root, value=current_label)
            self._hotkey_vars[fkey] = var

            combo = ttk.Combobox(
                row_frame,
                textvariable=var,
                values=action_labels,
                state="readonly",
                style="Dark.TCombobox",
                width=17,
                font=_FONT_SMALL,
            )
            combo.set(current_label)
            combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
            self._combos[fkey] = combo

            # Clear button
            def _make_clear(k=fkey, v=var):
                return lambda: (v.set(_UNASSIGNED), self._combos[k].set(_UNASSIGNED) if k in self._combos else None)

            clear_btn = self._reg(tk.Button(
                row_frame,
                text="✕",
                font=_FONT_SMALL,
                bg=_BG_FIELD,
                fg=_DANGER,
                activebackground=_BG_HOVER,
                activeforeground=_DANGER,
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=_CARD_BORDER,
                cursor="hand2",
                command=_make_clear(fkey, var),
                width=2,
            ), "clear_btn")
            clear_btn.pack(side="left")

    def _build_osd_section(self, parent: tk.Frame, config: dict) -> None:
        """Build OSD card (left side of options row)."""
        card = self._reg(tk.Frame(
            parent,
            bg=_CARD_BG,
            highlightthickness=1,
            highlightbackground=_CARD_BORDER,
            padx=14,
            pady=10,
        ), "card_frame")
        card.pack(side="left", fill="both", expand=True, padx=(0, 6))

        self._reg(tk.Label(
            card,
            text="🖥  Notificaciones OSD",
            font=_FONT_HEADING,
            bg=_CARD_BG,
            fg=_ACCENT,
        ), "card_header").pack(anchor="w", pady=(0, 6))

        osd_data = config.get("osd", {})

        self._osd_enabled_var = tk.BooleanVar(master=self._root, value=osd_data.get("enabled", True))
        ttk.Checkbutton(
            card,
            text="Mostrar aviso visual en pantalla",
            variable=self._osd_enabled_var,
            style="Dark.TCheckbutton",
        ).pack(anchor="w", pady=(0, 6))

        dur_frame = self._reg(tk.Frame(card, bg=_CARD_BG), "card_frame")
        dur_frame.pack(fill="x")

        self._reg(tk.Label(
            dur_frame,
            text="Duración:",
            font=_FONT_SMALL,
            bg=_CARD_BG,
            fg=_FG_DIM,
        ), "dim_label").pack(side="left", padx=(0, 6))

        self._osd_duration_var = tk.IntVar(master=self._root, value=osd_data.get("duration_ms", 1000))

        dur_label = self._reg(tk.Label(
            dur_frame,
            text=f"{self._osd_duration_var.get()} ms",
            font=_FONT_BOLD,
            bg=_CARD_BG,
            fg=_ACCENT,
            width=8,
        ), "accent_value_label")
        dur_label.pack(side="right")

        dur_scale = ttk.Scale(
            dur_frame,
            from_=100,
            to=5000,
            orient="horizontal",
            variable=self._osd_duration_var,
            style="Dark.Horizontal.TScale",
            command=lambda val: dur_label.configure(text=f"{int(float(val))} ms"),
        )
        dur_scale.pack(side="left", fill="x", expand=True, padx=(0, 6))

    def _build_general_section(self, parent: tk.Frame, config: dict) -> None:
        """Build General settings card (right side of options row)."""
        card = self._reg(tk.Frame(
            parent,
            bg=_CARD_BG,
            highlightthickness=1,
            highlightbackground=_CARD_BORDER,
            padx=14,
            pady=10,
        ), "card_frame")
        card.pack(side="left", fill="both", expand=True, padx=(6, 0))

        self._reg(tk.Label(
            card,
            text="⚙  General y Apariencia",
            font=_FONT_HEADING,
            bg=_CARD_BG,
            fg=_ACCENT,
        ), "card_header").pack(anchor="w", pady=(0, 6))

        # Theme selector
        theme_row = self._reg(tk.Frame(card, bg=_CARD_BG), "card_frame")
        theme_row.pack(fill="x", pady=(0, 6))

        self._reg(tk.Label(
            theme_row,
            text="Tema visual:",
            font=_FONT,
            bg=_CARD_BG,
            fg=_FG_DIM,
        ), "dim_label").pack(side="left", padx=(0, 8))

        theme_labels = {"dark": "🌙 Oscuro", "light": "☀️ Claro"}
        inv_theme_labels = {v: k for k, v in theme_labels.items()}

        current_theme = config.get("theme", "dark")
        if current_theme not in THEMES:
            current_theme = "dark"
        self._current_theme = current_theme

        self._theme_var = tk.StringVar(
            master=self._root,
            value=theme_labels.get(current_theme, "🌙 Oscuro")
        )
        theme_combo = ttk.Combobox(
            theme_row,
            textvariable=self._theme_var,
            values=["🌙 Oscuro", "☀️ Claro"],
            state="readonly",
            style="Dark.TCombobox",
            width=12,
            font=_FONT_SMALL,
        )
        theme_combo.pack(side="left")

        def _on_theme_select(event=None):
            selected = self._theme_var.get() if self._theme_var else "🌙 Oscuro"
            selected_theme = inv_theme_labels.get(selected, "dark")
            self._apply_theme(selected_theme)

        theme_combo.bind("<<ComboboxSelected>>", _on_theme_select)

        self._app_enabled_var = tk.BooleanVar(master=self._root, value=config.get("enabled", True))
        ttk.Checkbutton(
            card,
            text="Iniciar con hotkeys activos",
            variable=self._app_enabled_var,
            style="Dark.TCheckbutton",
        ).pack(anchor="w", pady=(0, 4))

        autostart_current = self._autostart_manager.is_enabled()
        self._autostart_var = tk.BooleanVar(master=self._root, value=autostart_current)
        ttk.Checkbutton(
            card,
            text="Iniciar con Windows (inicio automático)",
            variable=self._autostart_var,
            style="Dark.TCheckbutton",
        ).pack(anchor="w")

    def _build_buttons(self, parent: tk.Frame) -> None:
        """Build action buttons bar at bottom."""
        btn_frame = self._reg(tk.Frame(parent, bg=_BG), "bg_frame")
        btn_frame.pack(fill="x", pady=(14, 0))

        # Reset defaults
        self._reg(tk.Button(
            btn_frame,
            text="↺  Restaurar valores",
            font=_FONT,
            bg=_BG_FIELD,
            fg=_FG_DIM,
            activebackground=_BG_HOVER,
            activeforeground=_FG,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=_CARD_BORDER,
            cursor="hand2",
            padx=14,
            pady=6,
            command=self._reset_defaults,
        ), "field_btn").pack(side="left")

        # Discrete About Me button
        self._reg(tk.Button(
            btn_frame,
            text="ℹ  Acerca de",
            font=_FONT,
            bg=_BG_FIELD,
            fg=_FG_DIM,
            activebackground=_BG_HOVER,
            activeforeground=_FG,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=_CARD_BORDER,
            cursor="hand2",
            padx=12,
            pady=6,
            command=self._open_about,
        ), "field_btn").pack(side="left", padx=(8, 0))

        # Cancel
        self._reg(tk.Button(
            btn_frame,
            text="✕  Cancelar",
            font=_FONT,
            bg=_BG_FIELD,
            fg=_FG,
            activebackground=_BG_HOVER,
            activeforeground=_FG,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=_CARD_BORDER,
            cursor="hand2",
            padx=16,
            pady=6,
            command=self._on_close,
        ), "cancel_btn").pack(side="right", padx=(8, 0))

        # Save (styled with --active forest green matching .btn-download from landing_v3.html)
        self._reg(tk.Button(
            btn_frame,
            text="💾  Guardar cambios",
            font=_FONT_BOLD,
            bg=_ACCENT,
            fg="#ffffff",
            activebackground=_ACCENT_HOVER,
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=22,
            pady=6,
            command=self._save,
        ), "save_btn").pack(side="right")

    def _collect_config(self) -> dict:
        """Collect current UI state into a config dictionary."""
        hotkeys = {}
        for fkey in _FKEYS:
            label = ""
            if fkey in self._hotkey_vars:
                label = self._hotkey_vars[fkey].get()
            if (not label or label == _UNASSIGNED) and fkey in self._combos:
                combo_val = self._combos[fkey].get()
                if combo_val:
                    label = combo_val

            if label and label != _UNASSIGNED:
                action_value = _LABEL_TO_ACTION.get(label)
                if action_value:
                    hotkeys[fkey] = action_value

        theme_label = self._theme_var.get() if self._theme_var else "🌙 Oscuro"
        theme_val = "light" if "Claro" in theme_label else "dark"

        return {
            "schema_version": SCHEMA_VERSION,
            "theme": theme_val,
            "enabled": self._app_enabled_var.get() if self._app_enabled_var else True,
            "osd": {
                "enabled": self._osd_enabled_var.get() if self._osd_enabled_var else True,
                "duration_ms": self._osd_duration_var.get() if self._osd_duration_var else 1000,
            },
            "hotkeys": hotkeys,
        }

    def _save(self) -> None:
        """Validate and save the configuration."""
        config_dict = self._collect_config()

        try:
            write_config_atomic(config_dict, self._config_path)
            logger.info("Settings saved to %s", self._config_path)

            # Apply autostart setting
            if self._autostart_var is not None:
                want_autostart = self._autostart_var.get()
                current_autostart = self._autostart_manager.is_enabled()
                if want_autostart and not current_autostart:
                    self._autostart_manager.enable()
                elif not want_autostart and current_autostart:
                    self._autostart_manager.disable()

            self._on_close()
        except Exception as e:
            logger.exception("Failed to save settings")
            messagebox.showerror(
                "Error",
                f"No se pudo guardar la configuración:\n{e}",
                parent=self._root,
            )

    def _reset_defaults(self) -> None:
        """Reset all fields to default values."""
        defaults = _default_config_dict()

        # Reset hotkeys
        default_hotkeys = defaults.get("hotkeys", {})
        for fkey in _FKEYS:
            action_value = default_hotkeys.get(fkey, "")
            label = _ACTION_LABELS.get(action_value, _UNASSIGNED)
            if fkey in self._hotkey_vars:
                self._hotkey_vars[fkey].set(label)
            if fkey in self._combos:
                self._combos[fkey].set(label)

        # Reset OSD
        osd_defaults = defaults.get("osd", {})
        if self._osd_enabled_var:
            self._osd_enabled_var.set(osd_defaults.get("enabled", True))
        if self._osd_duration_var:
            self._osd_duration_var.set(osd_defaults.get("duration_ms", 1000))

        # Reset theme
        if self._theme_var:
            self._theme_var.set("🌙 Oscuro")
        self._apply_theme("dark")

        # Reset enabled
        if self._app_enabled_var:
            self._app_enabled_var.set(defaults.get("enabled", True))

        # Reset autostart
        if self._autostart_var:
            self._autostart_var.set(False)

    def _on_close(self) -> None:
        """Close the settings window."""
        with self._lock:
            SettingsWindow._instance = None

        if self._root:
            try:
                self._root.quit()
            except Exception:
                pass
            try:
                self._root.destroy()
            except Exception:
                pass
            self._root = None
