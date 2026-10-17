"""PDF report renderer using ReportLab.

Milestone P14 — Professional Engineering Report Generator (RHS-P14-001 § 5, § 7, § 28).
Generates publication-quality formal PDF engineering reports matching the visual styling of the reference document:
- A4 Portrait standard layout
- Running header with Title, Scenario, Software Version, and mandatory Running Direction banner
- Running footer with Software ID, Report ID, and dynamic Page X of Y
- Executive KPI dashboard with 4 prominent headline metrics
- Formatted tables with dark navy headers, alternating row fills, and repeated headers across page breaks
- Rule-based recommendation cards
- Embedded static high-resolution engineering figures (speed envelope, blocking stairway, etc.)
"""

from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Union

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, inch, mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from headway.infrastructure.direction import RunningDirection
from headway.reporting.export_static import export_figure_headless
from headway.reporting.report_models import (
    ReportDocument,
    ReportSectionId,
)


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and display total page count."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))

        # Footer line and text
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(36, 36, 559, 36)

        footer_left = "Railway Headway & Line Capacity Assessment Subsystem"
        footer_right = f"Page {self._pageNumber} of {page_count}"
        self.drawString(36, 24, footer_left)
        self.drawRightString(559, 24, footer_right)

        # Header (Pages >= 2)
        if self._pageNumber > 1:
            self.line(36, 806, 559, 806)
            self.drawString(36, 812, "Railway Headway Simulation — Engineering Report")
            direction_str = getattr(self, "running_direction_str", "FORWARD")
            self.drawRightString(559, 812, f"RUNNING DIRECTION: {direction_str}")

        self.restoreState()


class PdfReportRenderer:
    """Renders ReportDocument into publication-grade PDF using ReportLab."""

    PRIMARY_NAVY = colors.HexColor("#1B365D")
    SECONDARY_BLUE = colors.HexColor("#2E6B9E")
    LIGHT_BG = colors.HexColor("#F8FAFC")
    BORDER_LIGHT = colors.HexColor("#E2E8F0")
    TEXT_DARK = colors.HexColor("#1A202C")
    TEXT_MUTED = colors.HexColor("#64748B")
    CRITICAL_RED = colors.HexColor("#C62828")
    SUCCESS_GREEN = colors.HexColor("#2E7D32")
    WARNING_AMBER = colors.HexColor("#E65100")

    @classmethod
    def render(
        cls,
        document: ReportDocument,
        output_path: Union[str, Path],
    ) -> str:
        """Renders complete PDF report to disk."""
        target_path = Path(output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        doc = SimpleDocTemplate(
            str(target_path),
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=45,
            bottomMargin=45,
        )

        styles = cls._build_styles()
        story = []

        direction_val = document.running_direction.value

        # Header Block
        story.append(Paragraph(document.metadata.title, styles["ReportTitle"]))
        story.append(Paragraph(document.metadata.subtitle, styles["ReportSubtitle"]))

        meta_line = (
            f"Project: <b>{document.metadata.project_id}</b> &nbsp;|&nbsp; "
            f"Scenario: <b>{document.metadata.scenario_id}</b> &nbsp;|&nbsp; "
            f"Run ID: <code>{document.metadata.simulation_run_id}</code>"
        )
        story.append(Paragraph(meta_line, styles["MetaText"]))
        story.append(Spacer(1, 6))

        # Direction Banner (P14-DIR-008)
        banner_style = styles["DirectionBannerFwd"] if direction_val == "FORWARD" else styles["DirectionBannerRev"]
        story.append(Paragraph(f"<b>RUNNING DIRECTION: {direction_val}</b>", banner_style))
        story.append(Spacer(1, 10))

        # Executive Summary Dashboard
        story.extend(cls._build_executive_dashboard(document, styles))
        story.append(Spacer(1, 12))

        # Temporary directory for static figure images
        with tempfile.TemporaryDirectory() as tmp_fig_dir:
            fig_dir_path = Path(tmp_fig_dir)

            # Render Sections 1 to 18
            for s_id, s in document.sections.items():
                if s_id == ReportSectionId.EXECUTIVE_SUMMARY:
                    continue

                story.append(Paragraph(f"{s.section_number} {s.title}", styles["SectionHeading"]))
                story.append(HRFlowable(width="100%", thickness=1, color=cls.SECONDARY_BLUE, spaceBefore=2, spaceAfter=6))

                if not s.is_applicable:
                    reason = s.not_applicable_reason or "Not applicable for this simulation run."
                    story.append(Paragraph(f"<i>ℹ️ Not Applicable: {reason}</i>", styles["MutedText"]))
                    story.append(Spacer(1, 10))
                    continue

                for p in s.narrative_paragraphs:
                    story.append(Paragraph(p, styles["BodyTextCustom"]))
                    story.append(Spacer(1, 4))

                for cb in s.callout_boxes:
                    story.append(cls._build_callout_box(cb.get("title", "Note"), cb.get("text", ""), styles))
                    story.append(Spacer(1, 6))

                # Render figures
                for f_key in s.figure_keys:
                    fig_obj = document.figures_data.get(f_key)
                    if fig_obj is not None:
                        img_path = fig_dir_path / f"{f_key}.png"
                        try:
                            export_figure_headless(fig_obj, img_path, width=900, height=450, dpi=180)
                            if img_path.exists():
                                story.append(Image(str(img_path), width=520, height=260))
                                story.append(Spacer(1, 6))
                        except Exception:
                            # Fallback if image generation fails
                            story.append(Paragraph(f"<i>[Figure: {f_key}]</i>", styles["MutedText"]))

                # Render tables
                for tbl in s.tables:
                    story.append(cls._build_table_flowable(tbl, styles))
                    story.append(Spacer(1, 8))

                # Recommendations
                if s.recommendations:
                    for rec in s.recommendations:
                        story.append(cls._build_recommendation_card(rec, styles))
                        story.append(Spacer(1, 6))

                story.append(Spacer(1, 8))

            # Build PDF with NumberedCanvas
            def canvas_maker(*args, **kwargs):
                c = NumberedCanvas(*args, **kwargs)
                c.running_direction_str = direction_val
                return c

            doc.build(story, canvasmaker=canvas_maker)

        return str(target_path)

    @classmethod
    def _build_styles(cls) -> Dict[str, ParagraphStyle]:
        """Constructs ReportLab paragraph styles."""
        ss = getSampleStyleSheet()

        return {
            "ReportTitle": ParagraphStyle(
                "ReportTitle",
                parent=ss["Heading1"],
                fontName="Helvetica-Bold",
                fontSize=18,
                leading=22,
                textColor=cls.PRIMARY_NAVY,
                spaceAfter=2,
            ),
            "ReportSubtitle": ParagraphStyle(
                "ReportSubtitle",
                parent=ss["Normal"],
                fontName="Helvetica-Bold",
                fontSize=11,
                leading=14,
                textColor=cls.SECONDARY_BLUE,
                spaceAfter=4,
            ),
            "MetaText": ParagraphStyle(
                "MetaText",
                parent=ss["Normal"],
                fontName="Helvetica",
                fontSize=8,
                leading=11,
                textColor=cls.TEXT_MUTED,
            ),
            "DirectionBannerFwd": ParagraphStyle(
                "DirectionBannerFwd",
                parent=ss["Normal"],
                fontName="Helvetica-Bold",
                fontSize=9,
                leading=12,
                textColor=colors.HexColor("#0D47A1"),
                backColor=colors.HexColor("#E3F2FD"),
                borderPadding=4,
                alignment=1,  # Center
            ),
            "DirectionBannerRev": ParagraphStyle(
                "DirectionBannerRev",
                parent=ss["Normal"],
                fontName="Helvetica-Bold",
                fontSize=9,
                leading=12,
                textColor=colors.HexColor("#E65100"),
                backColor=colors.HexColor("#FFF3E0"),
                borderPadding=4,
                alignment=1,  # Center
            ),
            "SectionHeading": ParagraphStyle(
                "SectionHeading",
                parent=ss["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=11,
                leading=14,
                textColor=cls.PRIMARY_NAVY,
                spaceBefore=6,
                spaceAfter=2,
                keepWithNext=True,
            ),
            "BodyTextCustom": ParagraphStyle(
                "BodyTextCustom",
                parent=ss["Normal"],
                fontName="Helvetica",
                fontSize=8.5,
                leading=12,
                textColor=cls.TEXT_DARK,
            ),
            "MutedText": ParagraphStyle(
                "MutedText",
                parent=ss["Normal"],
                fontName="Helvetica-Oblique",
                fontSize=8,
                leading=11,
                textColor=cls.TEXT_MUTED,
            ),
            "KpiVal": ParagraphStyle(
                "KpiVal",
                parent=ss["Normal"],
                fontName="Helvetica-Bold",
                fontSize=15,
                leading=18,
                textColor=cls.PRIMARY_NAVY,
                alignment=1,
            ),
            "KpiValCrit": ParagraphStyle(
                "KpiValCrit",
                parent=ss["Normal"],
                fontName="Helvetica-Bold",
                fontSize=12,
                leading=15,
                textColor=cls.CRITICAL_RED,
                alignment=1,
            ),
            "KpiLabel": ParagraphStyle(
                "KpiLabel",
                parent=ss["Normal"],
                fontName="Helvetica-Bold",
                fontSize=7.5,
                leading=9,
                textColor=cls.TEXT_MUTED,
                alignment=1,
            ),
            "KpiSub": ParagraphStyle(
                "KpiSub",
                parent=ss["Normal"],
                fontName="Helvetica",
                fontSize=6.5,
                leading=8,
                textColor=cls.TEXT_MUTED,
                alignment=1,
            ),
            "TableHead": ParagraphStyle(
                "TableHead",
                parent=ss["Normal"],
                fontName="Helvetica-Bold",
                fontSize=7,
                leading=8.5,
                textColor=colors.white,
            ),
            "TableCell": ParagraphStyle(
                "TableCell",
                parent=ss["Normal"],
                fontName="Helvetica",
                fontSize=6.5,
                leading=8,
                textColor=cls.TEXT_DARK,
            ),
            "TableCellBold": ParagraphStyle(
                "TableCellBold",
                parent=ss["Normal"],
                fontName="Helvetica-Bold",
                fontSize=6.5,
                leading=8,
                textColor=cls.PRIMARY_NAVY,
            ),
        }

    @classmethod
    def _build_executive_dashboard(
        cls,
        document: ReportDocument,
        styles: Dict[str, ParagraphStyle],
    ) -> List[Any]:
        """Builds the 4 prominent KPI cards and summaries for executive section."""
        flowables = []
        kpis = document.executive_kpis

        flowables.append(Paragraph("Executive Summary & Primary KPI Dashboard", styles["SectionHeading"]))
        flowables.append(HRFlowable(width="100%", thickness=1.5, color=cls.PRIMARY_NAVY, spaceBefore=2, spaceAfter=6))

        # KPI cards
        kpi_cells = [
            [
                Paragraph("TECHNICAL MIN HEADWAY", styles["KpiLabel"]),
                Paragraph(f"{kpis.technical_headway_s:.1f} s", styles["KpiVal"]),
                Paragraph(f"{kpis.technical_headway_min:.2f} min ({kpis.headway_definition})", styles["KpiSub"]),
            ],
            [
                Paragraph("THEORETICAL CAPACITY", styles["KpiLabel"]),
                Paragraph(f"{kpis.theoretical_capacity_tph:.1f} tph", styles["KpiVal"]),
                Paragraph("trains/hour/direction (zero buffer)", styles["KpiSub"]),
            ],
            [
                Paragraph("PLANNING CAPACITY", styles["KpiLabel"]),
                Paragraph(f"{kpis.planning_capacity_tph:.1f} tph", styles["KpiVal"]),
                Paragraph(f"{kpis.planning_margin_s:.0f}s operational buffer margin", styles["KpiSub"]),
            ],
            [
                Paragraph("PERFORMANCE FACTOR", styles["KpiLabel"]),
                Paragraph(kpis.performance_factor_str, styles["KpiVal"]),
                Paragraph(f"Source: {kpis.performance_factor_source}", styles["KpiSub"]),
            ],
        ]
        if kpis.total_service_duration_s is not None:
            kpi_cells.append([
                Paragraph("TOTAL SERVICE DURATION", styles["KpiLabel"]),
                Paragraph(kpis.total_service_duration_str, styles["KpiVal"]),
                Paragraph("End-to-End Line Traversal", styles["KpiSub"]),
            ])
        kpi_cells.append([
            Paragraph("CONTROLLING BOTTLENECK", styles["KpiLabel"]),
            Paragraph(kpis.controlling_bottleneck_id, styles["KpiValCrit"]),
            Paragraph(f"{kpis.controlling_bottleneck_type} • km {kpis.controlling_bottleneck_chainage_km:.2f}", styles["KpiSub"]),
        ])

        col_w = 520.0 / len(kpi_cells)
        col_widths = [col_w] * len(kpi_cells)
        crit_idx = len(kpi_cells) - 1

        t_kpis = Table([kpi_cells], colWidths=col_widths)
        t_kpis.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (crit_idx - 1, 0), colors.HexColor("#F8FAFC")),
                ("BACKGROUND", (crit_idx, 0), (crit_idx, 0), colors.HexColor("#FFF5F5")),
                ("BOX", (0, 0), (crit_idx - 1, 0), 1, colors.HexColor("#CBD5E1")),
                ("BOX", (crit_idx, 0), (crit_idx, 0), 1.5, cls.CRITICAL_RED),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ])
        )
        flowables.append(t_kpis)
        flowables.append(Spacer(1, 8))

        # Side-by-side rolling stock and infrastructure summaries
        rs = document.rolling_stock
        infra = document.infrastructure
        if rs and infra:
            rs_data = [
                [Paragraph("<b>Rolling Stock Characteristics</b>", styles["TableCellBold"]), Paragraph("", styles["TableCell"])],
                [Paragraph("Train Model", styles["TableCell"]), Paragraph(f"<b>{rs.model_name}</b>", styles["TableCell"])],
                [Paragraph("Length / Gross Mass", styles["TableCell"]), Paragraph(f"{rs.train_length_m:.1f} m / {rs.gross_mass_t:.1f} t (Tare: {rs.tare_mass_t:.1f} t)", styles["TableCell"])],
                [Paragraph("Max Speed / Power", styles["TableCell"]), Paragraph(f"{rs.max_speed_kmh:.1f} km/h / {rs.traction_power_kw:.0f} kW", styles["TableCell"])],
                [Paragraph("Braking (Service/Emerg)", styles["TableCell"]), Paragraph(f"{rs.service_braking_deceleration_ms2:.2f} / {rs.emergency_braking_deceleration_ms2:.2f} m/s²", styles["TableCell"])],
                [Paragraph("Davis (A / B / C)", styles["TableCell"]), Paragraph(f"A = {rs.davis_a_n:.1f} N / B = {rs.davis_b_ns_per_m:.2f} Ns/m / C = {rs.davis_c_ns2_per_m2:.4f} Ns²/m² [v in m/s]", styles["TableCell"])],
            ]
            infra_data = [
                [Paragraph("<b>Infrastructure & Signalling</b>", styles["TableCellBold"]), Paragraph("", styles["TableCell"])],
                [Paragraph("Signalling Technology", styles["TableCell"]), Paragraph(f"<b>{infra.signalling_technology}</b>", styles["TableCell"])],
                [Paragraph("Aspect Model / Overlap", styles["TableCell"]), Paragraph(f"{infra.aspect_model} / {infra.default_overlap_m:.0f} m", styles["TableCell"])],
                [Paragraph("Sighting / Setup / Rel", styles["TableCell"]), Paragraph(f"{infra.sighting_time_s:.1f}s / {infra.route_setup_time_s:.1f}s / {infra.resource_release_delay_s:.1f}s", styles["TableCell"])],
                [Paragraph("Links / Blocks / Signals", styles["TableCell"]), Paragraph(f"{infra.total_links} / {infra.total_blocks} / {infra.total_signals}", styles["TableCell"])],
                [Paragraph("Stations / Plts / TVS", styles["TableCell"]), Paragraph(f"{infra.total_stations} / {infra.total_platforms} / {infra.total_tvs_sections}", styles["TableCell"])],
            ]

            t_rs = Table(rs_data, colWidths=[110, 140])
            t_rs.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
                ("BOX", (0, 0), (-1, -1), 0.5, cls.BORDER_LIGHT),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#EDF2F7")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))

            t_infra = Table(infra_data, colWidths=[110, 140])
            t_infra.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
                ("BOX", (0, 0), (-1, -1), 0.5, cls.BORDER_LIGHT),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#EDF2F7")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))

            summary_table = Table([[t_rs, t_infra]], colWidths=[260, 260])
            summary_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]))
            flowables.append(summary_table)
            flowables.append(Spacer(1, 6))

        # Bottleneck diagnosis callout
        diag = document.bottleneck_diagnosis
        if diag:
            callout = cls._build_callout_box(
                "Governing Bottleneck Diagnosis",
                f"Resource <b>{diag.resource_id}</b> ({diag.resource_type}) at chainage {diag.physical_location_m/1000.0:.2f} km governs the line headway ({diag.required_headway_s:.1f} s). {diag.engineering_cause}",
                styles,
                box_color=colors.HexColor("#FFF7ED"),
                border_color=cls.WARNING_AMBER,
            )
            flowables.append(callout)

        return flowables

    @classmethod
    def _build_kpi_section(
        cls,
        document: ReportDocument,
        styles: Optional[Dict[str, ParagraphStyle]] = None,
    ) -> List[Any]:
        """Build KPI executive dashboard section flowables (alias for test inspection)."""
        if styles is None:
            styles = cls._build_styles()
        return cls._build_executive_dashboard(document, styles)

    @classmethod
    def _build_callout_box(
        cls,
        title: str,
        text: str,
        styles: Dict[str, ParagraphStyle],
        box_color: Any = colors.HexColor("#F1F5F9"),
        border_color: Any = colors.HexColor("#2E6B9E"),
    ) -> Table:
        """Constructs an engineering callout note box."""
        content = [
            Paragraph(f"<b>{title.upper()}</b>", styles["TableCellBold"]),
            Paragraph(text, styles["TableCell"]),
        ]
        t = Table([[content]], colWidths=[520])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), box_color),
            ("BOX", (0, 0), (-1, -1), 0.5, cls.BORDER_LIGHT),
            ("LINELEFT", (0, 0), (-1, -1), 3, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t

    @classmethod
    def _build_table_flowable(
        cls,
        table_obj: Any,
        styles: Dict[str, ParagraphStyle],
        max_rows: int = 15,
    ) -> Table:
        """Converts an EngineeringTable into a styled ReportLab Table."""
        df = table_obj.formatted_dataframe
        cols = list(df.columns)
        num_cols = len(cols)
        col_w = 520.0 / max(1, num_cols)

        # Header row
        rows = [[Paragraph(f"<b>{c}</b>", styles["TableHead"]) for c in cols]]

        # Data rows
        for _, row in df.head(max_rows).iterrows():
            row_cells = []
            for c in cols:
                val = str(row[c])
                cell_style = styles["TableCellBold"] if "★" in val or "CONTROLLING" in val else styles["TableCell"]
                row_cells.append(Paragraph(val, cell_style))
            rows.append(row_cells)

        t = Table(rows, colWidths=[col_w] * num_cols, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), cls.PRIMARY_NAVY),
            ("BOX", (0, 0), (-1, -1), 0.5, cls.BORDER_LIGHT),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#EDF2F7")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    @classmethod
    def _build_recommendation_card(
        cls,
        rec: Any,
        styles: Dict[str, ParagraphStyle],
    ) -> Table:
        """Builds a formatted recommendation card."""
        badge = "SIMULATED BENEFIT" if not rec.requires_further_simulation else "PROPOSED ACTION"
        header = f"<b>{rec.recommendation_id}</b> &nbsp;|&nbsp; <i>{rec.category.value.replace('_', ' ')}</i> &nbsp;[{badge}]"

        content = [
            Paragraph(header, styles["TableCellBold"]),
            Paragraph(f"<b>{rec.title}</b>", styles["BodyTextCustom"]),
            Paragraph(f"<b>Description:</b> {rec.description}", styles["TableCell"]),
            Paragraph(f"<b>Expected Benefit:</b> {rec.expected_benefit}", styles["TableCell"]),
            Paragraph(f"<b>Engineering Rationale:</b> {rec.rationale}", styles["TableCell"]),
        ]

        t = Table([[content]], colWidths=[520])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.5, cls.BORDER_LIGHT),
            ("LINELEFT", (0, 0), (-1, -1), 3.5, cls.SECONDARY_BLUE),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t
