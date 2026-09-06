"""Compatibility analyzer: produces structured diagnostic reports.

Analyzes the collected SystemInfo to identify potential issues
(OEM conflicts, admin elevation, AV interference) without
blocking app startup — all findings are informational.
"""

import logging
from typing import List

from src.models.system import (
    CompatibilityFinding,
    CompatibilityReport,
    FindingSeverity,
    SystemInfo,
)

logger = logging.getLogger(__name__)


def analyze_compatibility(system_info: SystemInfo) -> CompatibilityReport:
    """Analyze system compatibility and produce a report.

    Args:
        system_info: The collected SystemInfo snapshot.

    Returns:
        A CompatibilityReport with structured findings (SAFE/WARNING).
    """
    report = CompatibilityReport(system_info=system_info)

    # Check admin/elevation status
    if system_info.is_admin:
        report.add(CompatibilityFinding(
            component="elevation",
            severity=FindingSeverity.WARNING,
            message=(
                "WinMediaDeck is running as Administrator. "
                "This is not required and may cause issues with "
                "the session-scoped mutex if another instance runs "
                "at a different integrity level."
            ),
            recommendation=(
                "Run WinMediaDeck as a standard user unless "
                "you have a specific reason to elevate."
            ),
        ))
    else:
        report.add(CompatibilityFinding(
            component="elevation",
            severity=FindingSeverity.SAFE,
            message="Running as standard user (recommended).",
        ))

    # Check DPI awareness
    if system_info.dpi_awareness == "unaware":
        report.add(CompatibilityFinding(
            component="dpi",
            severity=FindingSeverity.WARNING,
            message=(
                "DPI awareness is 'unaware'. OSD overlay may render "
                "at incorrect sizes on high-DPI monitors."
            ),
            recommendation=(
                "The application should call SetProcessDpiAwarenessContext "
                "early in startup."
            ),
        ))
    else:
        report.add(CompatibilityFinding(
            component="dpi",
            severity=FindingSeverity.SAFE,
            message=f"DPI awareness: {system_info.dpi_awareness}",
        ))

    # Check display count
    if system_info.display_count > 1:
        report.add(CompatibilityFinding(
            component="display",
            severity=FindingSeverity.SAFE,
            message=(
                f"Multi-monitor setup detected ({system_info.display_count} displays). "
                "OSD will appear on the monitor containing the cursor."
            ),
        ))
    else:
        report.add(CompatibilityFinding(
            component="display",
            severity=FindingSeverity.SAFE,
            message="Single monitor detected.",
        ))

    # Check antivirus
    if system_info.antivirus:
        av_name = system_info.antivirus.lower()
        # Known AV products that may flag keyboard hooks
        suspicious_av = ["kaspersky", "bitdefender", "norton", "avast", "avg"]
        is_suspicious = any(av in av_name for av in suspicious_av)

        if is_suspicious:
            report.add(CompatibilityFinding(
                component="antivirus",
                severity=FindingSeverity.WARNING,
                message=(
                    f"Antivirus detected: {system_info.antivirus}. "
                    "This AV may flag WinMediaDeck's keyboard hook as suspicious."
                ),
                recommendation=(
                    "If the hook fails to install, add WinMediaDeck "
                    "to your AV's exclusion list."
                ),
            ))
        else:
            report.add(CompatibilityFinding(
                component="antivirus",
                severity=FindingSeverity.SAFE,
                message=f"Antivirus detected: {system_info.antivirus}",
            ))

    # Check OS version
    try:
        build = system_info.os_build
        if build < 17763:  # Windows 10 1809
            report.add(CompatibilityFinding(
                component="os",
                severity=FindingSeverity.WARNING,
                message=(
                    f"OS build {build} is older than Windows 10 1809. "
                    "Some features may not work correctly."
                ),
                recommendation="Update to Windows 10 version 1809 or later.",
            ))
        else:
            report.add(CompatibilityFinding(
                component="os",
                severity=FindingSeverity.SAFE,
                message=f"OS version {system_info.os_version} (build {build})",
            ))
    except (ValueError, TypeError):
        report.add(CompatibilityFinding(
            component="os",
            severity=FindingSeverity.SAFE,
            message=f"OS version {system_info.os_version}",
        ))

    return report


def format_report(report: CompatibilityReport) -> str:
    """Format a CompatibilityReport as a human-readable string.

    Args:
        report: The report to format.

    Returns:
        A multi-line string suitable for console output.
    """
    lines = [
        "╔══════════════════════════════════════════════════════════╗",
        "║          WinMediaDeck — Compatibility Report            ║",
        "╚══════════════════════════════════════════════════════════╝",
        "",
        f"  OS:          {report.system_info.os_version}",
        f"  Python:      {report.system_info.python_version}",
        f"  Admin:       {'Yes' if report.system_info.is_admin else 'No'}",
        f"  Integrity:   {report.system_info.integrity_level}",
        f"  Displays:    {report.system_info.display_count}",
        f"  DPI:         {report.system_info.dpi_awareness}",
        f"  Antivirus:   {report.system_info.antivirus or 'Not detected'}",
        "",
        "─────────────────────────────────────────────────────────────",
        "",
    ]

    for finding in report.findings:
        icon = "✓" if finding.severity == FindingSeverity.SAFE else "⚠"
        lines.append(f"  [{icon}] {finding.component}: {finding.message}")
        if finding.recommendation:
            lines.append(f"      → {finding.recommendation}")
        lines.append("")

    if report.has_warnings:
        lines.append("  Result: Some issues found. See warnings above.")
    else:
        lines.append("  Result: All checks passed ✓")

    return "\n".join(lines)
