"""CLI interactive diagnostic for WinMediaDeck.

Runs system detection, compatibility analysis, and optional
latency/hook verification tests.
"""

import sys
import time
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.system_detector import detect_system
from src.core.compatibility import analyze_compatibility, format_report
from src.config.settings import load_config, get_config_path, ConfigurationError


def run_diagnostic() -> None:
    """Run the full diagnostic suite."""
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║         WinMediaDeck — Diagnóstico Interactivo         ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # 1. System detection
    print("[1/3] Detectando sistema...")
    system_info = detect_system()
    report = analyze_compatibility(system_info)
    print(format_report(report))
    print()

    # 2. Config validation
    print("─" * 60)
    print("[2/3] Validando configuración...")
    config_path = get_config_path()
    print(f"  Ruta: {config_path}")

    try:
        settings = load_config()
        print(f"  Schema: v{settings.schema_version}")
        print(f"  Enabled: {settings.enabled}")
        print(f"  OSD: {'activado' if settings.osd.enabled else 'desactivado'} "
              f"({settings.osd.duration_ms}ms)")
        print(f"  Hotkeys configurados: {len(settings.hotkeys)}")
        for key, action in sorted(settings.hotkeys.items()):
            print(f"    {key} → {action.value}")
        print("  ✓ Configuración válida")
    except ConfigurationError as e:
        print(f"  ✗ Error: {e}")
    print()

    # 3. Hook latency test
    print("─" * 60)
    print("[3/3] Test de latencia del hook...")
    print("  (Estimando overhead de ctypes...)")

    import ctypes
    times = []
    for _ in range(1000):
        start = time.perf_counter_ns()
        # Simulate the critical path: GetAsyncKeyState for a VK
        ctypes.windll.user32.GetAsyncKeyState(0x70)
        elapsed = time.perf_counter_ns() - start
        times.append(elapsed)

    avg_ns = sum(times) / len(times)
    max_ns = max(times)
    p99_ns = sorted(times)[int(0.99 * len(times))]

    print(f"  Promedio: {avg_ns / 1000:.1f} µs")
    print(f"  P99:      {p99_ns / 1000:.1f} µs")
    print(f"  Máximo:   {max_ns / 1000:.1f} µs")

    if max_ns < 500_000:  # 0.5 ms
        print("  ✓ Latencia dentro del presupuesto (< 0.5 ms)")
    else:
        print("  ⚠ Latencia máxima excede 0.5 ms — monitorear en producción")

    print()
    print("═" * 60)
    print("  Diagnóstico completo.")
    print("═" * 60)


if __name__ == "__main__":
    run_diagnostic()
