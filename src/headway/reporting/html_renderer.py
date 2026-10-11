"""HTML report renderer.

Milestone P14 — Professional Engineering Report Generator (RHS-P14-001 § 5, § 7, § 28).
Renders ReportDocument into a self-contained, publication-ready HTML5 engineering document.
Matches visual styling of reference engineering report:
- Professional executive dashboard with 4 prominent KPI cards
- Dark navy headers (#1B365D), medium blue accents (#2E6B9E), green/amber/red status badges
- Clear running direction banner: 'Running Direction: FORWARD' or 'Running Direction: REVERSE'
- Structured data tables with alternating row shading and explicit SI units
- Rule-based recommendation cards with category badges and verification tags
- Print-optimized CSS for clean browser printing and PDF conversion
"""

from pathlib import Path
from typing import Any, Dict, Optional, Union
import html

from headway.reporting.report_models import ReportDocument, ReportSectionId


class HtmlReportRenderer:
    """Renders ReportDocument into standalone HTML5."""

    @classmethod
    def render(
        cls,
        document: ReportDocument,
        output_path: Optional[Union[str, Path]] = None,
        embed_interactive_plotly: bool = True,
    ) -> str:
        """Renders complete HTML report string and optionally writes to disk."""
        meta = document.metadata
        kpis = document.executive_kpis
        rs = document.rolling_stock
        infra = document.infrastructure
        diag = document.bottleneck_diagnosis
        direction_val = document.running_direction.value

        direction_badge_class = "badge-forward" if direction_val == "FORWARD" else "badge-reverse"

        html_parts = []
        html_parts.append("<!DOCTYPE html>")
        html_parts.append("<html lang='en'>")
        html_parts.append("<head>")
        html_parts.append("<meta charset='UTF-8'>")
        html_parts.append("<meta name='viewport' content='width=device-width, initial-scale=1.0'>")
        html_parts.append(f"<title>{html.escape(meta.title)} — {html.escape(meta.scenario_id)} [{direction_val}]</title>")
        html_parts.append("<style>")
        html_parts.append(cls._get_css_styles())
        html_parts.append("</style>")
        html_parts.append("</head>")
        html_parts.append("<body>")

        # Top Header Banner
        html_parts.append("<header class='report-header'>")
        html_parts.append("<div class='header-left'>")
        html_parts.append(f"<h1 class='report-title'>{html.escape(meta.title)}</h1>")
        html_parts.append(f"<div class='report-subtitle'>{html.escape(meta.subtitle)}</div>")
        html_parts.append(f"<div class='report-meta-line'>Project: <b>{html.escape(meta.project_id)}</b> &nbsp;|&nbsp; Scenario: <b>{html.escape(meta.scenario_id)}</b> &nbsp;|&nbsp; Run: <code>{html.escape(meta.simulation_run_id)}</code></div>")
        html_parts.append("</div>")
        html_parts.append("<div class='header-right'>")
        html_parts.append(f"<div class='direction-banner {direction_badge_class}'>RUNNING DIRECTION: {direction_val}</div>")
        html_parts.append(f"<div class='software-ver'>Software: {html.escape(meta.software_version)} &nbsp;|&nbsp; Date: {meta.generation_time[:10]}</div>")
        html_parts.append(f"<div class='hash-badge'>Config Hash: <code>{meta.input_configuration_hash[:12]}...</code></div>")
        html_parts.append("</div>")
        html_parts.append("</header>")

        # Executive Summary Section & KPI Dashboard
        html_parts.append("<section class='section-container' id='sec-executive'>")
        html_parts.append("<div class='section-header'>")
        html_parts.append("<h2 class='section-title'>Executive Summary & Headline KPIs</h2>")
        html_parts.append("</div>")

        # 4 Headline KPI Cards (P14-EXE-001)
        html_parts.append("<div class='kpi-grid'>")
        html_parts.append(f"""
        <div class='kpi-card'>
            <div class='kpi-label'>Technical Minimum Headway</div>
            <div class='kpi-value'>{kpis.technical_headway_s:.1f} <span class='kpi-unit'>s</span></div>
            <div class='kpi-subtext'>{kpis.technical_headway_min:.2f} min &nbsp;•&nbsp; {html.escape(kpis.headway_definition)}</div>
        </div>
        <div class='kpi-card'>
            <div class='kpi-label'>Theoretical Capacity</div>
            <div class='kpi-value'>{kpis.theoretical_capacity_tph:.1f} <span class='kpi-unit'>tph</span></div>
            <div class='kpi-subtext'>trains/hour/direction (zero buffer)</div>
        </div>
        <div class='kpi-card'>
            <div class='kpi-label'>Planning Operational Capacity</div>
            <div class='kpi-value'>{kpis.planning_capacity_tph:.1f} <span class='kpi-unit'>tph</span></div>
            <div class='kpi-subtext'>under {kpis.planning_margin_s:.0f}s operational buffer margin</div>
        </div>
        <div class='kpi-card kpi-card-critical'>
            <div class='kpi-label'>Controlling Bottleneck</div>
            <div class='kpi-value-sm'>{html.escape(kpis.controlling_bottleneck_id)}</div>
            <div class='kpi-subtext'>{html.escape(kpis.controlling_bottleneck_type)} &nbsp;•&nbsp; km {kpis.controlling_bottleneck_chainage_km:.2f}</div>
        </div>
        """)
        html_parts.append("</div>")

        # Rolling Stock & Infrastructure Summaries (P14-EXE-003 & 004)
        html_parts.append("<div class='two-col-grid'>")
        if rs:
            html_parts.append(f"""
            <div class='summary-box'>
                <h3 class='box-title'>Rolling Stock Characteristics</h3>
                <table class='summary-table'>
                    <tr><td>Train Model</td><td><b>{html.escape(rs.model_name)}</b></td></tr>
                    <tr><td>Length / Gross Mass</td><td>{rs.train_length_m:.1f} m &nbsp;/&nbsp; {rs.gross_mass_t:.1f} t</td></tr>
                    <tr><td>Max Speed / Power</td><td>{rs.max_speed_kmh:.1f} km/h &nbsp;/&nbsp; {rs.traction_power_kw:.0f} kW</td></tr>
                    <tr><td>Service / Emergency Brake</td><td>{rs.service_braking_deceleration_ms2:.2f} / {rs.emergency_braking_deceleration_ms2:.2f} m/s²</td></tr>
                    <tr><td>Davis Resistance</td><td>{rs.davis_a_n:.0f} N + {rs.davis_b_ns_per_m:.1f}v + {rs.davis_c_ns2_per_m2:.3f}v²</td></tr>
                </table>
            </div>
            """)

        if infra:
            html_parts.append(f"""
            <div class='summary-box'>
                <h3 class='box-title'>Infrastructure & Signalling Parameters</h3>
                <table class='summary-table'>
                    <tr><td>Signalling Technology</td><td><b>{html.escape(infra.signalling_technology)}</b></td></tr>
                    <tr><td>Topology / Corridor</td><td>{html.escape(infra.topology_mode)}</td></tr>
                    <tr><td>Dataset & Version</td><td>{html.escape(infra.dataset_id)} (v{html.escape(infra.dataset_version)})</td></tr>
                    <tr><td>Route Setup / Release Delay</td><td>{infra.route_setup_time_s:.1f} s &nbsp;/&nbsp; {infra.resource_release_delay_s:.1f} s</td></tr>
                    <tr><td>Simulation Fidelity</td><td>{html.escape(infra.model_fidelity)}</td></tr>
                </table>
            </div>
            """)
        html_parts.append("</div>")

        # Bottleneck Diagnosis Box (P14-EXE-005)
        if diag:
            html_parts.append(f"""
            <div class='callout-box callout-warning'>
                <div class='callout-title'>Governing Bottleneck Diagnosis</div>
                <div class='callout-body'>
                    Resource <b>{html.escape(diag.resource_id)}</b> ({html.escape(diag.resource_type)}) at chainage {diag.physical_location_m/1000.0:.2f} km governs the corridor capacity.
                    Total required temporal headway is <b>{diag.required_headway_s:.1f} s</b>.
                    Slack margin to second most restrictive conflict is {diag.slack_to_second_s:.1f} s.
                    <div style='margin-top: 6px;'><b>Engineering Cause:</b> {html.escape(diag.engineering_cause)}</div>
                </div>
            </div>
            """)

        html_parts.append("</section>")

        # Render All Standard Sections (Sections 1 to 18)
        for s_id, s in document.sections.items():
            if s_id == ReportSectionId.EXECUTIVE_SUMMARY:
                continue

            html_parts.append(f"<section class='section-container' id='sec-{s_id.value.lower()}'>")
            html_parts.append("<div class='section-header'>")
            html_parts.append(f"<h2 class='section-title'>{html.escape(s.section_number)} {html.escape(s.title)}</h2>")
            html_parts.append("</div>")

            if not s.is_applicable:
                reason = s.not_applicable_reason or "Section not applicable for this simulation run configuration."
                html_parts.append(f"<div class='not-applicable-box'>ℹ️ <b>Not Applicable:</b> {html.escape(reason)}</div>")
                html_parts.append("</section>")
                continue

            # Narrative paragraphs
            for p in s.narrative_paragraphs:
                html_parts.append(f"<p class='narrative-text'>{html.escape(p)}</p>")

            # Callout boxes
            for cb in s.callout_boxes:
                html_parts.append(f"""
                <div class='callout-box'>
                    <div class='callout-title'>{html.escape(cb.get('title', 'Note'))}</div>
                    <div class='callout-body'>{html.escape(cb.get('text', ''))}</div>
                </div>
                """)

            # Figures
            for f_key in s.figure_keys:
                fig_obj = document.figures_data.get(f_key)
                if fig_obj is not None:
                    html_parts.append("<div class='figure-wrapper'>")
                    if hasattr(fig_obj, "to_html") and embed_interactive_plotly:
                        html_parts.append(fig_obj.to_html(full_html=False, include_plotlyjs="cdn"))
                    else:
                        html_parts.append(f"<div class='figure-placeholder'>Figure: {html.escape(f_key)}</div>")
                    html_parts.append("</div>")

            # Tables
            for tbl in s.tables:
                html_parts.append("<div class='table-wrapper'>")
                html_parts.append(f"<div class='table-title'>{html.escape(tbl.title)}</div>")
                html_parts.append(tbl.to_html(formatted=True))
                html_parts.append("</div>")

            # Recommendations (for Section 18)
            if s.recommendations:
                html_parts.append("<div class='recommendations-list'>")
                for rec in s.recommendations:
                    sim_tag = "SIMULATED BENEFIT" if not rec.requires_further_simulation else "PROPOSED ACTION"
                    sim_badge = "badge-success" if not rec.requires_further_simulation else "badge-info"
                    html_parts.append(f"""
                    <div class='recommendation-card'>
                        <div class='rec-header'>
                            <span class='rec-id'>{html.escape(rec.recommendation_id)}</span>
                            <span class='rec-category'>{html.escape(rec.category.value.replace('_', ' '))}</span>
                            <span class='rec-status {sim_badge}'>{sim_tag}</span>
                        </div>
                        <h4 class='rec-title'>{html.escape(rec.title)}</h4>
                        <div class='rec-desc'>{html.escape(rec.description)}</div>
                        <div class='rec-benefit'><b>Expected Benefit:</b> {html.escape(rec.expected_benefit)}</div>
                        <div class='rec-rationale'><b>Rationale:</b> {html.escape(rec.rationale)}</div>
                        {f"<div class='rec-limitations'><i>Note: {html.escape(rec.assumptions_and_limitations)}</i></div>" if rec.assumptions_and_limitations else ""}
                    </div>
                    """)
                html_parts.append("</div>")

            html_parts.append("</section>")

        # Footer
        html_parts.append("<footer class='report-footer'>")
        html_parts.append(f"<div>{html.escape(meta.organization)} — Headway & Capacity Simulation Subsystem v{html.escape(meta.software_version)}</div>")
        html_parts.append(f"<div>Report ID: <code>{html.escape(meta.report_id)}</code> &nbsp;|&nbsp; Hash: <code>{meta.input_configuration_hash}</code></div>")
        html_parts.append("</footer>")

        html_parts.append("</body>")
        html_parts.append("</html>")

        full_html = "\n".join(html_parts)

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(full_html, encoding="utf-8")

        return full_html

    @classmethod
    def _get_css_styles(cls) -> str:
        """Standard CSS styling matching the reference engineering report."""
        return """
        :root {
            --primary-navy: #1B365D;
            --secondary-blue: #2E6B9E;
            --accent-teal: #008080;
            --critical-red: #C62828;
            --warning-amber: #E65100;
            --success-green: #2E7D32;
            --bg-light: #F8F9FA;
            --border-light: #E2E8F0;
            --text-dark: #1A202C;
            --text-muted: #64748B;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            color: var(--text-dark);
            background-color: #FFFFFF;
            margin: 0;
            padding: 30px 45px;
            line-height: 1.5;
            font-size: 14px;
        }

        .report-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            border-bottom: 3px solid var(--primary-navy);
            padding-bottom: 16px;
            margin-bottom: 24px;
        }

        .report-title {
            font-size: 24px;
            font-weight: 700;
            color: var(--primary-navy);
            margin: 0 0 4px 0;
            letter-spacing: -0.3px;
        }

        .report-subtitle {
            font-size: 14px;
            color: var(--secondary-blue);
            font-weight: 600;
            margin-bottom: 8px;
        }

        .report-meta-line {
            font-size: 12px;
            color: var(--text-muted);
        }

        .direction-banner {
            font-size: 12px;
            font-weight: 700;
            padding: 6px 14px;
            border-radius: 4px;
            text-align: center;
            letter-spacing: 0.5px;
            text-transform: uppercase;
            margin-bottom: 6px;
        }

        .badge-forward {
            background-color: #E3F2FD;
            color: #0D47A1;
            border: 1px solid #90CAF9;
        }

        .badge-reverse {
            background-color: #FFF3E0;
            color: #E65100;
            border: 1px solid #FFCC80;
        }

        .software-ver, .hash-badge {
            font-size: 11px;
            color: var(--text-muted);
            text-align: right;
            margin-top: 2px;
        }

        .section-container {
            margin-bottom: 32px;
            page-break-inside: avoid;
        }

        .section-header {
            border-bottom: 1.5px solid var(--secondary-blue);
            margin-bottom: 14px;
            padding-bottom: 4px;
        }

        .section-title {
            font-size: 16px;
            font-weight: 700;
            color: var(--primary-navy);
            margin: 0;
            text-transform: uppercase;
            letter-spacing: 0.4px;
        }

        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 20px;
        }

        .kpi-card {
            background-color: #F8FAFC;
            border: 1px solid var(--border-light);
            border-top: 4px solid var(--primary-navy);
            border-radius: 4px;
            padding: 14px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }

        .kpi-card-critical {
            border-top-color: var(--critical-red);
            background-color: #FFF5F5;
        }

        .kpi-label {
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            color: var(--text-muted);
            margin-bottom: 6px;
        }

        .kpi-value {
            font-size: 26px;
            font-weight: 800;
            color: var(--primary-navy);
            line-height: 1.1;
        }

        .kpi-value-sm {
            font-size: 18px;
            font-weight: 800;
            color: var(--critical-red);
            line-height: 1.2;
            word-break: break-all;
        }

        .kpi-unit {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-muted);
        }

        .kpi-subtext {
            font-size: 11px;
            color: var(--text-muted);
            margin-top: 4px;
        }

        .two-col-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 20px;
        }

        .summary-box {
            background-color: #FFFFFF;
            border: 1px solid var(--border-light);
            border-radius: 4px;
            padding: 14px;
        }

        .box-title {
            font-size: 13px;
            font-weight: 700;
            color: var(--primary-navy);
            margin: 0 0 10px 0;
            border-bottom: 1px solid var(--border-light);
            padding-bottom: 4px;
        }

        .summary-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }

        .summary-table td {
            padding: 4px 6px;
            border-bottom: 1px solid #EDF2F7;
        }

        .summary-table td:first-child {
            color: var(--text-muted);
            width: 45%;
        }

        .callout-box {
            background-color: #F1F5F9;
            border-left: 4px solid var(--secondary-blue);
            padding: 12px 16px;
            border-radius: 0 4px 4px 0;
            margin-bottom: 18px;
        }

        .callout-warning {
            background-color: #FFF7ED;
            border-left-color: var(--warning-amber);
        }

        .callout-title {
            font-size: 12px;
            font-weight: 700;
            color: var(--primary-navy);
            margin-bottom: 4px;
            text-transform: uppercase;
        }

        .callout-body {
            font-size: 12px;
            color: var(--text-dark);
        }

        .narrative-text {
            font-size: 13px;
            color: var(--text-dark);
            margin-bottom: 12px;
        }

        .not-applicable-box {
            background-color: #F8FAFC;
            border: 1px dashed var(--border-light);
            padding: 12px 16px;
            color: var(--text-muted);
            font-size: 12px;
            border-radius: 4px;
        }

        .table-wrapper {
            margin: 14px 0 20px 0;
            overflow-x: auto;
        }

        .table-title {
            font-size: 12px;
            font-weight: 700;
            color: var(--primary-navy);
            margin-bottom: 6px;
        }

        table.engineering-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
            text-align: left;
        }

        table.engineering-table th {
            background-color: var(--primary-navy);
            color: #FFFFFF;
            font-weight: 600;
            padding: 6px 10px;
            border: 1px solid var(--primary-navy);
        }

        table.engineering-table td {
            padding: 5px 10px;
            border: 1px solid var(--border-light);
        }

        table.engineering-table tr:nth-child(even) {
            background-color: #F8FAFC;
        }

        table.engineering-table tr:hover {
            background-color: #EDF2F7;
        }

        .figure-wrapper {
            margin: 16px 0 24px 0;
            text-align: center;
        }

        .recommendation-card {
            background-color: #FFFFFF;
            border: 1px solid var(--border-light);
            border-left: 4px solid var(--secondary-blue);
            border-radius: 4px;
            padding: 14px 18px;
            margin-bottom: 14px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        }

        .rec-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 6px;
        }

        .rec-id {
            font-size: 11px;
            font-weight: 700;
            color: var(--primary-navy);
        }

        .rec-category {
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            color: var(--text-muted);
            background: #EDF2F7;
            padding: 2px 6px;
            border-radius: 3px;
        }

        .rec-status {
            font-size: 9px;
            font-weight: 700;
            text-transform: uppercase;
            padding: 2px 6px;
            border-radius: 3px;
        }

        .badge-success { background: #E8F5E9; color: #2E7D32; }
        .badge-info { background: #E1F5FE; color: #0288D1; }

        .rec-title {
            font-size: 13px;
            font-weight: 700;
            color: var(--primary-navy);
            margin: 0 0 6px 0;
        }

        .rec-desc, .rec-benefit, .rec-rationale, .rec-limitations {
            font-size: 12px;
            margin-bottom: 4px;
        }

        .report-footer {
            margin-top: 40px;
            border-top: 1px solid var(--border-light);
            padding-top: 14px;
            font-size: 11px;
            color: var(--text-muted);
            display: flex;
            justify-content: space-between;
        }

        @media print {
            body { padding: 0; font-size: 12px; }
            .section-container { page-break-inside: avoid; }
            .report-header { page-break-after: avoid; }
        }
        """
