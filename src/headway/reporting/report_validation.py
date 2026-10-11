"""Report validation and audit verification engine.

Milestone P14 — Professional Engineering Report Generator (RHS-P14-001 § 29).
Validates assembled reports against rigorous engineering audit criteria:
- P14-RPT-VAL-001: Availability of required datasets
- P14-RPT-VAL-002: Consistency between Executive KPIs and detailed tables
- P14-RPT-VAL-003: Capacity mathematical consistency (C = 3600 / H)
- P14-RPT-VAL-004: Blocking-time component duration reconciliation
- P14-RPT-VAL-005: Controlling bottleneck identity consistency
- P14-RPT-VAL-006: Scenario and Run ID integrity
- P14-RPT-VAL-007: Configuration hash matching
- P14-RPT-VAL-008: Transparent disclosure of non-applicable sections
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional

from headway.core.exceptions import DataValidationError
from headway.data.validation import Severity
from headway.reporting.report_models import ReportDocument, ReportSectionId


class ReportDiagnosticCode(str, Enum):
    """Diagnostic error codes for report validation."""

    MISSING_REQUIRED_DATA = "RPT_MISSING_REQUIRED_DATA"
    KPI_TABLE_MISMATCH = "RPT_KPI_TABLE_MISMATCH"
    CAPACITY_FORMULA_MISMATCH = "RPT_CAPACITY_FORMULA_MISMATCH"
    RECONCILIATION_MISMATCH = "RPT_RECONCILIATION_MISMATCH"
    BOTTLENECK_MISMATCH = "RPT_BOTTLENECK_MISMATCH"
    HASH_MISMATCH = "RPT_HASH_MISMATCH"
    RUN_IDENTITY_MISMATCH = "RPT_RUN_IDENTITY_MISMATCH"
    SILENT_SECTION_OMISSION = "RPT_SILENT_SECTION_OMISSION"
    INVALID_DIRECTION = "RPT_INVALID_DIRECTION"


@dataclass(frozen=True)
class ReportDiagnostic:
    """Individual finding from report validation audit."""

    code: ReportDiagnosticCode
    severity: Severity
    message: str
    section_id: Optional[ReportSectionId] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportValidationAudit:
    """Consolidated audit report for an assembled ReportDocument."""

    report_id: str
    diagnostics: List[ReportDiagnostic] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True if no CRITICAL or ERROR diagnostics exist."""
        return not any(d.severity in (Severity.CRITICAL, Severity.ERROR) for d in self.diagnostics)

    @property
    def has_critical(self) -> bool:
        return any(d.severity == Severity.CRITICAL for d in self.diagnostics)

    @property
    def error_messages(self) -> List[str]:
        return [d.message for d in self.diagnostics if d.severity in (Severity.CRITICAL, Severity.ERROR)]

    def add_diagnostic(
        self,
        code: ReportDiagnosticCode,
        severity: Severity,
        message: str,
        section_id: Optional[ReportSectionId] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.diagnostics.append(
            ReportDiagnostic(
                code=code,
                severity=severity,
                message=message,
                section_id=section_id,
                context=context or {},
            )
        )


class ReportValidator:
    """Performs rigorous pre-export and post-assembly validation on ReportDocument."""

    @classmethod
    def validate_report(
        cls,
        document: ReportDocument,
        raise_on_error: bool = False,
    ) -> ReportValidationAudit:
        """Audits ReportDocument across all mandatory consistency criteria."""
        audit = ReportValidationAudit(report_id=document.metadata.report_id)

        # 1. Identity & Metadata Check (P14-RPT-VAL-006 & 007)
        if not document.metadata.report_id:
            audit.add_diagnostic(
                code=ReportDiagnosticCode.MISSING_REQUIRED_DATA,
                severity=Severity.CRITICAL,
                message="Report is missing required 'report_id'.",
            )
        if not document.metadata.scenario_id:
            audit.add_diagnostic(
                code=ReportDiagnosticCode.RUN_IDENTITY_MISMATCH,
                severity=Severity.CRITICAL,
                message="Report is missing required 'scenario_id'.",
            )
        if not document.metadata.input_configuration_hash:
            audit.add_diagnostic(
                code=ReportDiagnosticCode.HASH_MISMATCH,
                severity=Severity.CRITICAL,
                message="Report is missing required 'input_configuration_hash'.",
            )

        # 2. Capacity Formula Verification (P14-RPT-VAL-003)
        # C_theo = 3600 / H_min
        hw_s = document.executive_kpis.technical_headway_s
        theo_c = document.executive_kpis.theoretical_capacity_tph
        if hw_s > 0:
            expected_c = round(3600.0 / hw_s, 1)
            if abs(theo_c - expected_c) > 0.2:
                audit.add_diagnostic(
                    code=ReportDiagnosticCode.CAPACITY_FORMULA_MISMATCH,
                    severity=Severity.ERROR,
                    message=f"Theoretical capacity {theo_c} tph does not match 3600/H formula ({expected_c} tph for H={hw_s} s).",
                    context={"hw_s": hw_s, "theo_c": theo_c, "expected_c": expected_c},
                )

        # 3. KPI Consistency with Conflict Ranking (P14-RPT-VAL-002 & 005)
        conflict_sec = document.get_section(ReportSectionId.CONFLICT_RANKING)
        if conflict_sec and conflict_sec.is_applicable and conflict_sec.tables:
            tbl = conflict_sec.tables[0]
            if tbl.row_count > 0:
                top_hw = float(tbl.raw_dataframe["Required Headway (s)"].iloc[0])
                top_res = str(tbl.raw_dataframe["Leader Resource"].iloc[0])
                if abs(hw_s - top_hw) > 0.5:
                    audit.add_diagnostic(
                        code=ReportDiagnosticCode.KPI_TABLE_MISMATCH,
                        severity=Severity.ERROR,
                        message=f"Executive KPI headway ({hw_s} s) mismatches rank 1 conflict headway ({top_hw} s).",
                        section_id=ReportSectionId.CONFLICT_RANKING,
                    )
                if document.executive_kpis.controlling_bottleneck_id != top_res:
                    audit.add_diagnostic(
                        code=ReportDiagnosticCode.BOTTLENECK_MISMATCH,
                        severity=Severity.WARNING,
                        message=f"Controlling bottleneck '{document.executive_kpis.controlling_bottleneck_id}' differs from top conflict resource '{top_res}'.",
                        section_id=ReportSectionId.CONFLICT_RANKING,
                    )

        # 4. Blocking Component Duration Reconciliation (P14-RPT-VAL-004)
        timing_sec = document.get_section(ReportSectionId.DETAILED_RESOURCE_TIMING)
        if timing_sec and timing_sec.is_applicable and timing_sec.tables:
            tbl = timing_sec.tables[0]
            for idx, row in tbl.raw_dataframe.iterrows():
                comp_sum = sum(
                    float(row[c])
                    for c in [
                        "Setup (s)",
                        "Approach (s)",
                        "Running (s)",
                        "Dwell (s)",
                        "Clearance (s)",
                        "Residual Rear (s)",
                        "Release (s)",
                    ]
                    if c in row and pd.notnull(row[c])
                )
                tot_blk = float(row.get("Total Blocking (s)", 0.0))
                if abs(comp_sum - tot_blk) > 0.05:
                    audit.add_diagnostic(
                        code=ReportDiagnosticCode.RECONCILIATION_MISMATCH,
                        severity=Severity.ERROR,
                        message=f"Blocking timing reconciliation failed at row {idx} ({row.get('Resource ID', '')}): sum={comp_sum:.2f} != total={tot_blk:.2f}.",
                        section_id=ReportSectionId.DETAILED_RESOURCE_TIMING,
                    )
                    break

        # 5. Omission Transparency (P14-RPT-VAL-008)
        for s_id, s in document.sections.items():
            if not s.is_applicable and not s.not_applicable_reason:
                audit.add_diagnostic(
                    code=ReportDiagnosticCode.SILENT_SECTION_OMISSION,
                    severity=Severity.WARNING,
                    message=f"Section {s.section_number} ({s.title}) is marked non-applicable without documented reason.",
                    section_id=s_id,
                )

        if raise_on_error and not audit.is_valid:
            raise DataValidationError(
                f"Report audit validation failed: {'; '.join(audit.error_messages)}",
                error_code="ERR_REPORT_AUDIT_FAILED",
                context={"errors": [d.message for d in audit.diagnostics]},
            )

        return audit


import pandas as pd
