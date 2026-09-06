"""System information and compatibility analysis models.

Used by SystemDetector and CompatibilityAnalyzer to produce
structured diagnostic reports without blocking app startup.
"""

from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Optional


@unique
class FindingSeverity(Enum):
    """Severity level for a compatibility finding."""
    SAFE = "safe"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class SystemInfo:
    """Immutable snapshot of the host system.

    Attributes:
        os_version: Windows version string (e.g. "10.0.19045").
        os_build: Build number.
        is_admin: Whether the process is running elevated.
        integrity_level: Token integrity level (Low/Medium/High/System).
        python_version: Python runtime version.
        display_count: Number of connected monitors.
        dpi_awareness: Current DPI awareness context.
        antivirus: Detected antivirus product name, if any.
    """
    os_version: str = ""
    os_build: int = 0
    is_admin: bool = False
    integrity_level: str = "Medium"
    python_version: str = ""
    display_count: int = 1
    dpi_awareness: str = "unaware"
    antivirus: Optional[str] = None


@dataclass(frozen=True, slots=True)
class CompatibilityFinding:
    """A single compatibility observation.

    Attributes:
        component: The subsystem this finding relates to (e.g. "hook", "tray").
        severity: SAFE or WARNING.
        message: Human-readable description.
        recommendation: Suggested remediation, if applicable.
    """
    component: str
    severity: FindingSeverity
    message: str
    recommendation: str = ""


@dataclass(slots=True)
class CompatibilityReport:
    """Aggregated compatibility analysis results.

    Attributes:
        system_info: The collected SystemInfo snapshot.
        findings: List of individual findings.
    """
    system_info: SystemInfo = field(default_factory=SystemInfo)
    findings: list[CompatibilityFinding] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        """True if any finding has WARNING severity."""
        return any(f.severity == FindingSeverity.WARNING for f in self.findings)

    def add(self, finding: CompatibilityFinding) -> None:
        """Append a finding to the report."""
        self.findings.append(finding)
