"""Report generation configuration models.

Milestone P14 — Professional Engineering Report Generator (RHS-P14-001 § 4, § 6, § 7, § 31).
Configures report scope, selected sections, paper formatting, branding, and export targets.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Union

from headway.infrastructure.direction import RunningDirection
from headway.reporting.report_models import ReportSectionId, ReportType


class PaperSize(str, Enum):
    A4 = "A4"
    LETTER = "LETTER"


class PageOrientation(str, Enum):
    PORTRAIT = "PORTRAIT"
    LANDSCAPE = "LANDSCAPE"


@dataclass
class ReportConfig:
    """P14-UI-002: User and programmatic configuration for engineering report generation."""

    report_type: ReportType = ReportType.DETAILED_ENGINEERING
    running_direction: Optional[RunningDirection] = None
    included_sections: Optional[List[ReportSectionId]] = None
    paper_size: PaperSize = PaperSize.A4
    orientation: PageOrientation = PageOrientation.PORTRAIT
    include_figures: bool = True
    include_interactive_html: bool = True
    max_table_rows_in_pdf: int = 15
    title: Optional[str] = None
    subtitle: Optional[str] = None
    project_name: Optional[str] = None
    corridor_name: Optional[str] = None
    author: Optional[str] = None
    organization: Optional[str] = None
    logo_path: Optional[Union[str, Path]] = None
    primary_color: str = "#1B365D"
    secondary_color: str = "#2E6B9E"
    top_n_conflicts: int = 10
    top_n_occupations: int = 10
    custom_metadata: Dict[str, Any] = field(default_factory=dict)

    def is_section_enabled(self, section_id: ReportSectionId) -> bool:
        """Determines whether a section is requested under the current config."""
        if self.included_sections is None:
            # Under None, include all sections compatible with the report_type
            return True
        return section_id in self.included_sections
