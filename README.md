# WinMediaDeck

WinMediaDeck is a lightweight Windows utility that remaps the F1-F12 function key row to media controls, system launchers, and user-defined shortcuts. It runs as a single process in the system tray, with no background services, no drivers, and no telemetry.

## Features

- F1-F12 key remapping: Assigns function keys to media controls and system tools.
- System tray integration: Displays current operational state (active, paused, blocked, error) with contextual controls.
- On-Screen Display (OSD): Semi-transparent visual overlay confirming action execution. Multi-monitor and DPI aware.
- Hot-reload: Automatically reloads mappings when configuration changes are saved (200ms debounce).
- Strict validation: Malformed or invalid configurations are rejected without interrupting runtime execution.
- Single instance protection: Session-scoped mutex prevents concurrent application instances.
- Zero disk logs: Debug tracing is output strictly to standard error. No log files are created.
- Diagnostic tooling: Built-in diagnostic mode (`--diagnostic`) verifies hook capabilities and system prerequisites.

## Architecture

The project structure is organized into modular layers with clear separation of concerns:

```
src/
|-- models/             Data models: actions, events, states
|-- interfaces/         Abstract contracts (IKeyboardHook, IMediaController, IOSDService)
|-- platform/windows/   Win32 ctypes bindings: keyboard hooks, input synthesis, mutex, monitor enumeration
|-- core/               Action router, hotkey manager, media controller
|-- config/             Configuration parser, schema validator, filesystem watcher
`-- ui/                 OSD overlay window, system tray implementation
```

## Security Model

- Closed Action Set: Only predefined actions within the system enum can be triggered. The application does not execute arbitrary shell commands, scripts, or external binaries.
- Strict Schema Validation: Configurations are checked against schema version constraints. If a configuration file contains unknown or invalid properties, the previous valid configuration remains active.
- Key Scope Isolation: The low-level hook inspects only virtual key codes 0x70 through 0x7B (F1 through F12). All other keystrokes pass through untouched and uninspected.
- No Keystroke Logging: The application never buffers, records, or exports keystrokes.
- Network Isolation: The application makes no network requests.

## About the Keyboard Hook

WinMediaDeck uses the Windows low-level keyboard hook interface (`WH_KEYBOARD_LL`) to intercept F1-F12 key events before they reach the active foreground window, translating them to the mapped media or system input via `SendInput`.

Technical parameters:
- Monitored range: Virtual keys 0x70 (VK_F1) through 0x7B (VK_F12).
- Non-monitored keys: All keys outside the specified range pass immediately to the next hook in the chain.
- Data retention: None. Keystrokes outside F1-F12 are neither inspected nor stored.

## Installation

### Prerequisites

- Windows 10 (version 1809 or higher) or Windows 11
- Python 3.11 or higher
- Standard user permissions (administrator rights are not required)

### Setup

Clone the repository and install runtime dependencies:

```bash
git clone https://github.com/JeremiasToledo24/WinMediaDeck.git
cd WinMediaDeck
pip install -r requirements.txt
```

Run the application:

```bash
python main.py
```

## Usage

Command-line invocation options:

```bash
# Run in system tray mode (standard execution)
python main.py

# Run with debug logging to stderr
python main.py --debug

# Run compatibility and environment diagnostics
python main.py --diagnostic

# Display application version
python main.py --version
```

## Configuration

Configuration is loaded from `%LOCALAPPDATA%\WinMediaDeck\config.json`. If the file does not exist, a default configuration is generated automatically on initial run.

### Default Configuration

```json
{
  "schema_version": 1,
  "enabled": true,
  "osd": {
    "enabled": true,
    "duration_ms": 1000
  },
  "hotkeys": {
    "F1": "volume_down",
    "F2": "volume_up",
    "F3": "mute",
    "F4": "previous",
    "F5": "play_pause",
    "F6": "next",
    "F7": "stop",
    "F8": "calculator",
    "F9": "browser",
    "F10": "media_select",
    "F11": "mail",
    "F12": "toggle_pause"
  }
}
```

### Action Reference

| Action Name | Description |
|---|---|
| `volume_down` | Decrements system master volume |
| `volume_up` | Increments system master volume |
| `mute` | Toggles system audio mute |
| `previous` | Sends previous track media command |
| `play_pause` | Toggles media playback state |
| `next` | Sends next track media command |
| `stop` | Stops current media playback |
| `calculator` | Launches default system calculator |
| `browser` | Launches default web browser |
| `mail` | Launches default email client |
| `media_select` | Invokes operating system media selection dialog |
| `toggle_pause` | Pauses or resumes WinMediaDeck hook interception |

## License

MIT License. See LICENSE for full terms.
