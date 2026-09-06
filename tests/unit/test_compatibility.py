"""Unit tests for compatibility analysis."""

import pytest

from src.core.compatibility import analyze_compatibility, format_report
from src.models.system import (
    SystemInfo,
    CompatibilityFinding,
    CompatibilityReport,
    FindingSeverity,
)


class TestCompatibilityAnalysis:
    """Tests for the compatibility analyzer."""

    def test_standard_user_is_safe(self):
        """Non-admin user produces a SAFE elevation finding."""
        info = SystemInfo(is_admin=False)
        report = analyze_compatibility(info)

        elevation = [f for f in report.findings if f.component == "elevation"]
        assert len(elevation) == 1
        assert elevation[0].severity == FindingSeverity.SAFE

    def test_admin_user_is_warning(self):
        """Admin user produces a WARNING elevation finding."""
        info = SystemInfo(is_admin=True)
        report = analyze_compatibility(info)

        elevation = [f for f in report.findings if f.component == "elevation"]
        assert len(elevation) == 1
        assert elevation[0].severity == FindingSeverity.WARNING

    def test_dpi_unaware_is_warning(self):
        """DPI unaware produces a WARNING."""
        info = SystemInfo(dpi_awareness="unaware")
        report = analyze_compatibility(info)

        dpi = [f for f in report.findings if f.component == "dpi"]
        assert len(dpi) == 1
        assert dpi[0].severity == FindingSeverity.WARNING

    def test_dpi_per_monitor_is_safe(self):
        """DPI per-monitor produces a SAFE finding."""
        info = SystemInfo(dpi_awareness="per-monitor")
        report = analyze_compatibility(info)

        dpi = [f for f in report.findings if f.component == "dpi"]
        assert len(dpi) == 1
        assert dpi[0].severity == FindingSeverity.SAFE

    def test_multi_monitor_is_safe(self):
        """Multi-monitor setup produces a SAFE finding."""
        info = SystemInfo(display_count=3)
        report = analyze_compatibility(info)

        display = [f for f in report.findings if f.component == "display"]
        assert len(display) == 1
        assert display[0].severity == FindingSeverity.SAFE

    def test_suspicious_av_is_warning(self):
        """Known-problematic AV produces a WARNING."""
        info = SystemInfo(antivirus="Kaspersky Total Security")
        report = analyze_compatibility(info)

        av = [f for f in report.findings if f.component == "antivirus"]
        assert len(av) == 1
        assert av[0].severity == FindingSeverity.WARNING

    def test_safe_av_is_safe(self):
        """Non-problematic AV produces a SAFE finding."""
        info = SystemInfo(antivirus="Windows Defender")
        report = analyze_compatibility(info)

        av = [f for f in report.findings if f.component == "antivirus"]
        assert len(av) == 1
        assert av[0].severity == FindingSeverity.SAFE

    def test_old_os_is_warning(self):
        """OS build below 17763 produces a WARNING."""
        info = SystemInfo(os_version="10.0.15063", os_build=15063)
        report = analyze_compatibility(info)

        os_findings = [f for f in report.findings if f.component == "os"]
        assert len(os_findings) == 1
        assert os_findings[0].severity == FindingSeverity.WARNING

    def test_modern_os_is_safe(self):
        """OS build >= 17763 produces a SAFE finding."""
        info = SystemInfo(os_version="10.0.19045", os_build=19045)
        report = analyze_compatibility(info)

        os_findings = [f for f in report.findings if f.component == "os"]
        assert len(os_findings) == 1
        assert os_findings[0].severity == FindingSeverity.SAFE

    def test_has_warnings_property(self):
        """has_warnings is True when any WARNING exists."""
        info = SystemInfo(is_admin=True)
        report = analyze_compatibility(info)
        assert report.has_warnings is True

    def test_format_report_output(self):
        """format_report produces a non-empty string."""
        info = SystemInfo(os_version="10.0.19045", os_build=19045)
        report = analyze_compatibility(info)
        output = format_report(report)
        assert "WinMediaDeck" in output
        assert len(output) > 100


class TestCompatibilityReport:
    """Tests for the CompatibilityReport dataclass."""

    def test_empty_report(self):
        """Empty report has no warnings."""
        report = CompatibilityReport()
        assert report.has_warnings is False
        assert len(report.findings) == 0

    def test_add_finding(self):
        """Adding a finding increases the count."""
        report = CompatibilityReport()
        report.add(CompatibilityFinding(
            component="test",
            severity=FindingSeverity.SAFE,
            message="All good",
        ))
        assert len(report.findings) == 1
