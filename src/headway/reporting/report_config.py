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
    A3 = "A3"
    A4 = "A4"
    LETTER = "LETTER"


class PageOrientation(str, Enum):
    PORTRAIT = "PORTRAIT"
    LANDSCAPE = "LANDSCAPE"


TEMPLATE_SECTIONS: Dict[ReportType, Set[ReportSectionId]] = {
    ReportType.DETAILED_ENGINEERING: set(ReportSectionId),
    ReportType.EXECUTIVE_SUMMARY: {
        ReportSectionId.EXECUTIVE_SUMMARY,
        ReportSectionId.ASSUMPTIONS_AUDIT,
        ReportSectionId.CONCLUSIONS_RECOMMENDATIONS,
    },
    ReportType.CAPACITY_ASSESSMENT: {
        ReportSectionId.EXECUTIVE_SUMMARY,
        ReportSectionId.BLOCKING_STAIRWAY,
        ReportSectionId.SEVEN_COMPONENT_BREAKDOWN,
        ReportSectionId.CONFLICT_RANKING,
        ReportSectionId.LONGEST_OCCUPATIONS,
        ReportSectionId.BLOCK_LENGTH_SENSITIVITY,
        ReportSectionId.DETAILED_RESOURCE_TIMING,
        ReportSectionId.ASSUMPTIONS_AUDIT,
        ReportSectionId.CONCLUSIONS_RECOMMENDATIONS,
    },
    ReportType.HEADWAY_ASSESSMENT: {
        ReportSectionId.EXECUTIVE_SUMMARY,
        ReportSectionId.SPEED_GRADIENT_CURVATURE,
        ReportSectionId.BLOCKING_STAIRWAY,
        ReportSectionId.SEVEN_COMPONENT_BREAKDOWN,
        ReportSectionId.CONFLICT_RANKING,
        ReportSectionId.DETAILED_RESOURCE_TIMING,
        ReportSectionId.ASSUMPTIONS_AUDIT,
        ReportSectionId.CONCLUSIONS_RECOMMENDATIONS,
    },
    ReportType.MIXED_TRAFFIC: {
        ReportSectionId.EXECUTIVE_SUMMARY,
        ReportSectionId.MIXED_TRAFFIC_MATRIX,
        ReportSectionId.OPERATIONAL_ASSESSMENT,
        ReportSectionId.ASSUMPTIONS_AUDIT,
        ReportSectionId.CONCLUSIONS_RECOMMENDATIONS,
    },
    ReportType.TVS_ASSESSMENT: {
        ReportSectionId.EXECUTIVE_SUMMARY,
        ReportSectionId.TVS_ASSESSMENT,
        ReportSectionId.ASSUMPTIONS_AUDIT,
        ReportSectionId.CONCLUSIONS_RECOMMENDATIONS,
    },
    ReportType.STOCHASTIC_ASSESSMENT: {
        ReportSectionId.EXECUTIVE_SUMMARY,
        ReportSectionId.STOCHASTIC_RELIABILITY,
        ReportSectionId.ASSUMPTIONS_AUDIT,
        ReportSectionId.CONCLUSIONS_RECOMMENDATIONS,
    },
    ReportType.SCENARIO_COMPARISON: {
        ReportSectionId.EXECUTIVE_SUMMARY,
        ReportSectionId.SCENARIO_COMPARISON,
        ReportSectionId.ASSUMPTIONS_AUDIT,
        ReportSectionId.CONCLUSIONS_RECOMMENDATIONS,
    },
    ReportType.VALIDATION_REPORT: {
        ReportSectionId.EXECUTIVE_SUMMARY,
        ReportSectionId.VERIFICATION_LIMITATIONS,
        ReportSectionId.ASSUMPTIONS_AUDIT,
        ReportSectionId.CONCLUSIONS_RECOMMENDATIONS,
    },
}

TEMPLATE_FRIENDLY_NAMES: Dict[str, ReportType] = {
    "Standard": ReportType.DETAILED_ENGINEERING,
    "Detailed Engineering (All Sections)": ReportType.DETAILED_ENGINEERING,
    "Executive Summary Only": ReportType.EXECUTIVE_SUMMARY,
    "Capacity Focus": ReportType.CAPACITY_ASSESSMENT,
    "Headway Assessment": ReportType.HEADWAY_ASSESSMENT,
    "Mixed Traffic": ReportType.MIXED_TRAFFIC,
    "TVS Assessment": ReportType.TVS_ASSESSMENT,
    "Stochastic Assessment": ReportType.STOCHASTIC_ASSESSMENT,
    "Scenario Comparison": ReportType.SCENARIO_COMPARISON,
    "Validation Report": ReportType.VALIDATION_REPORT,
    "Detailed Engineering": ReportType.DETAILED_ENGINEERING,
}


# v1.11.1 / Task 7: block-geometry consistency audit (ERR_BLOCK_LENGTH_MISMATCH).
# Ships OFF in v1.11.1 because the bundled examples 01, 04 and 07 contain known
# block/signal stationing defects (corrected in v1.11.2 / PR #64, which flips this
# default to True). The check itself is unconditional on chainage source when enabled.
VALIDATE_BLOCK_GEOMETRY_DEFAULT: bool = False


@dataclass
class ReportConfig:
    """P14-UI-002: User and programmatic configuration for engineering report generation."""

    report_type: Union[ReportType, str] = ReportType.DETAILED_ENGINEERING
    running_direction: Optional[RunningDirection] = None
    included_sections: Optional[List[ReportSectionId]] = None
    paper_size: PaperSize = PaperSize.A3
    orientation: PageOrientation = PageOrientation.LANDSCAPE
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
    validate_block_geometry: bool = VALIDATE_BLOCK_GEOMETRY_DEFAULT

    def __post_init__(self) -> None:
        if isinstance(self.report_type, str):
            if self.report_type in TEMPLATE_FRIENDLY_NAMES:
                self.report_type = TEMPLATE_FRIENDLY_NAMES[self.report_type]
            else:
                try:
                    self.report_type = ReportType(self.report_type)
                except ValueError:
                    self.report_type = ReportType.DETAILED_ENGINEERING

    def is_section_enabled(self, section_id: ReportSectionId) -> bool:
        """Determines whether a section is requested under the current config."""
        template_allowed = TEMPLATE_SECTIONS.get(self.report_type, set(ReportSectionId))
        if section_id not in template_allowed:
            return False
        if self.included_sections is None:
            return True
        return section_id in self.included_sections
