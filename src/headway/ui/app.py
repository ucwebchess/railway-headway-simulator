"""Main Gradio application factory for Railway Headway & Capacity Simulator.

Implements the ten required application navigation tabs and dashboard
in full compliance with P00-UI-001 through P00-UI-007.
"""

from typing import Optional
import gradio as gr

from headway.core.configuration import AppConfig
from headway.core.logging_config import get_logger
from headway.ui.components import (
    create_header,
    create_kpi_card,
    create_placeholder_tab,
    get_runtime_environment_summary,
)
from headway.ui.theme import ENGINEERING_CUSTOM_CSS, get_engineering_theme

logger = get_logger("ui.app")


def create_app(config: Optional[AppConfig] = None) -> gr.Blocks:
    """Construct and configure the Gradio Blocks user interface.

    Args:
        config: Application configuration. Defaults to AppConfig().

    Returns:
        gr.Blocks: Ready-to-launch Gradio application.
    """
    app_config = config or AppConfig()
    app_config.initialize_runtime()

    theme = get_engineering_theme()

    with gr.Blocks(
        title=f"{app_config.app_name} v{app_config.version}",
    ) as demo:
        # Attach engineering theme and CSS as attributes for use during launch()
        demo.app_theme = theme
        demo.app_css = ENGINEERING_CUSTOM_CSS

        # Header banner
        create_header(app_config)

        with gr.Tabs() as tabs:
            # TAB 1: Project Dashboard
            with gr.TabItem("1. Project Dashboard", id="tab_dashboard"):
                gr.Markdown("### Project Overview & System Status")

                # Executive KPI placeholders (Strictly non-invented, labeled as unavailable)
                gr.Markdown("#### Key Performance Indicators (Microscopic Simulation)")
                with gr.Row():
                    create_kpi_card("Technical Min Headway", "Unimpeded leader-follower time")
                    create_kpi_card("Theoretical Capacity", "Ideal homogeneous trains/hour")
                    create_kpi_card("Planning Operational Capacity", "With operational planning margin")
                with gr.Row():
                    create_kpi_card("Controlling Bottleneck", "Infrastructure conflict critical point")
                    create_kpi_card("TVS Occupation Status", "Tunnel Ventilation Section constraint")
                    create_kpi_card("Simulated Throughput", "Continuous multi-train operation")

                gr.Markdown("---")
                gr.Markdown("#### Runtime Environment & Architecture Diagnostic")

                with gr.Row():
                    with gr.Column(scale=2):
                        env_data = get_runtime_environment_summary(app_config)
                        env_table_data = [[k, v] for k, v in env_data.items()]
                        gr.Dataframe(
                            headers=["System Property", "Current Configuration / Status"],
                            value=env_table_data,
                            datatype=["str", "str"],
                            interactive=False,
                            label="Host Execution Environment",
                        )
                    with gr.Column(scale=1):
                        gr.Markdown("#### Governance & Roadmap Status")
                        milestone_data = [
                            ["P00", "Project Foundation & Colab Launcher", "ACTIVE (Current)"],
                            ["P01", "Canonical Data & Excel Input", "Authorized Next"],
                            ["P02", "Infrastructure Network Model", "Pending"],
                            ["P03", "Rolling Stock Physics", "Pending"],
                            ["P04", "Braking & Microscopic Dynamics", "Pending"],
                            ["P05", "Resource Engine & Fixed-Block Signalling", "Pending"],
                            ["P06", "ETCS Level 2 & CBTC Signalling", "Pending"],
                            ["P07", "Stations, Junctions & TVS Control", "Pending"],
                            ["P08", "Blocking Time & Headway Engine", "Pending"],
                            ["P09", "Multi-Train Operational Dispatch", "Pending"],
                            ["P10", "Capacity & UIC 406-Inspired Analysis", "Pending"],
                            ["P11", "Stochastic Simulation & Reliability", "Pending"],
                            ["P12", "Scenario Management & Sensitivity", "Pending"],
                            ["P13", "Engineering Visualization", "Pending"],
                            ["P14", "Professional Engineering Reporting", "Pending"],
                            ["P15", "Full UI Integration & Acceptance Verification", "Pending"],
                        ]
                        gr.Dataframe(
                            headers=["Milestone", "Subsystem Scope", "Status"],
                            value=milestone_data,
                            datatype=["str", "str", "str"],
                            interactive=False,
                            label="15-Prompt Development Sequence",
                        )

            # TAB 2: Data Import
            with gr.TabItem("2. Data Import", id="tab_import"):
                create_placeholder_tab(
                    tab_name="Data Import",
                    milestone_code="P01",
                    description=(
                        "Provides single-file Excel workbook uploads and complete ZIP project package extraction. "
                        "Ingests Infrastructure, Signalling, Rolling Stock, Operations, Headway Analysis, and Scenario workbooks."
                    ),
                    planned_capabilities=[
                        "6 standardized Excel workbook parsers with strict type and unit normalization",
                        "ZIP project archive extraction with security path sanitization",
                        "Raw input caching in immutable staging directories",
                        "Conversion into canonical JSON schemas",
                    ],
                )

            # TAB 3: Data Validation
            with gr.TabItem("3. Data Validation", id="tab_validation"):
                create_placeholder_tab(
                    tab_name="Data Validation",
                    milestone_code="P01",
                    description=(
                        "Performs comprehensive validation of uploaded railway datasets, cross-referencing identifiers, "
                        "geometry consistency, signalling compatibility, and train characteristics before simulation."
                    ),
                    planned_capabilities=[
                        "Cross-table referential integrity verification",
                        "Infrastructure geometry continuity and gradient validation",
                        "Signalling aspect and block sequence sanity checks",
                        "Detailed error and warning diagnostics summary table",
                    ],
                )

            # TAB 4: Infrastructure Explorer
            with gr.TabItem("4. Infrastructure Explorer", id="tab_infrastructure"):
                create_placeholder_tab(
                    tab_name="Infrastructure Explorer",
                    milestone_code="P02",
                    description=(
                        "Interactive visualization and exploration of the 1D physical railway network, tracks, links, "
                        "switches, junctions, stations, platforms, signalling blocks, and TVS resource boundaries."
                    ),
                    planned_capabilities=[
                        "Track link network graph and chainage mapping",
                        "Gradient and curvature profile viewer",
                        "Signal and block boundary localization",
                        "Tunnel ventilation section (TVS) layout inspection",
                    ],
                )

            # TAB 5: Rolling Stock & Signalling
            with gr.TabItem("5. Rolling Stock & Signalling", id="tab_rs_sig"):
                create_placeholder_tab(
                    tab_name="Rolling Stock & Signalling",
                    milestone_code="P03 / P05 / P06",
                    description=(
                        "Configuration and inspection of train dynamic characteristics (Davis resistance, mass, traction curves, "
                        "braking models) and signalling systems (2/3/4-aspect fixed block, ETCS Level 2, CBTC moving block)."
                    ),
                    planned_capabilities=[
                        "Tractive effort vs speed curve visualization",
                        "Braking deceleration models (service, protection, emergency)",
                        "Aspect sequence and overlap configuration",
                        "Movement authority limit inspectors",
                    ],
                )

            # TAB 6: Services & Operations
            with gr.TabItem("6. Services & Operations", id="tab_services"):
                create_placeholder_tab(
                    tab_name="Services & Operations",
                    milestone_code="P04 / P07",
                    description=(
                        "Operational service patterns, stopping definitions, platform dwell durations, dispatch intervals, "
                        "and mixed-traffic composition definitions."
                    ),
                    planned_capabilities=[
                        "Train service timetable and stopping pattern manager",
                        "Platform assignment and dwell time parameters",
                        "Dispatching priority and operational margin settings",
                    ],
                )

            # TAB 7: Scenario Manager
            with gr.TabItem("7. Scenario Manager", id="tab_scenarios"):
                create_placeholder_tab(
                    tab_name="Scenario Manager",
                    milestone_code="P12",
                    description=(
                        "Baseline scenario preservation, isolated scenario branching, parameter overriding, block-length "
                        "sensitivities, and scenario comparison matrices."
                    ),
                    planned_capabilities=[
                        "Immutable baseline scenario management",
                        "Signalling and block length alternative scenarios",
                        "Rolling stock variation comparisons",
                        "Side-by-side scenario delta inspection",
                    ],
                )

            # TAB 8: Simulation Control
            with gr.TabItem("8. Simulation Control", id="tab_simulation"):
                create_placeholder_tab(
                    tab_name="Simulation Control",
                    milestone_code="P04 / P07 / P09",
                    description=(
                        "Execution of microscopic numerical train trajectory integration, resource reservation/release logging, "
                        "and multi-train conflict dispatching."
                    ),
                    planned_capabilities=[
                        "Deterministic 0.1s time-step numerical integration engine",
                        "Continuous front and rear train-length resource occupation",
                        "Strict TVS single-train occupancy rule enforcement",
                        "Progress tracking and simulation abort controls",
                    ],
                )

            # TAB 9: Results & Comparison
            with gr.TabItem("9. Results & Comparison", id="tab_results"):
                create_placeholder_tab(
                    tab_name="Results & Comparison",
                    milestone_code="P08 / P10 / P11",
                    description=(
                        "Detailed engineering analysis including 7-component blocking-time stairways, pairwise conflict matrices, "
                        "bottleneck identification, TVS delays, and UIC 406-inspired capacity consumption."
                    ),
                    planned_capabilities=[
                        "Interactive blocking-time stairway diagrams (Plotly)",
                        "Seven-component blocking time additive breakdown table",
                        "Heterogeneous pairwise headway matrix H(i, j)",
                        "Stochastic Monte Carlo reliability distributions",
                    ],
                )

            # TAB 10: Reports & Export
            with gr.TabItem("10. Reports & Export", id="tab_reports"):
                create_placeholder_tab(
                    tab_name="Reports & Export",
                    milestone_code="P14",
                    description=(
                        "Generation of professional railway engineering reports mirroring the reference report standard. "
                        "Exports include PDF executive summaries, HTML interactive packages, Excel calculation books, and JSON data."
                    ),
                    planned_capabilities=[
                        "Reference report format executive PDF generator",
                        "Complete calculation provenance and assumption audit log",
                        "Raw simulation event log export (CSV / JSON)",
                        "Summary KPI tables and figure bundles",
                    ],
                )

    return demo
