"""Professional chart theme and styling standards.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 7).
Satisfies:
- P13-THM-001: Consistent professional visual style compatible with reference report.
- P13-THM-002: Axis labels with explicit engineering units.
- P13-THM-003: Clear legends and multi-series identification.
- P13-THM-004: Descriptive engineering titles.
- P13-THM-005: Running direction annotation (FORWARD / REVERSE).
- P13-THM-006: Visual consistency across all diagrams.
- P13-THM-007: Controlling resource and bottleneck annotations.
"""

from typing import Any, Dict, Optional, Tuple
import matplotlib as mpl
import matplotlib.pyplot as plt
import plotly.graph_objects as go

from headway.infrastructure.direction import RunningDirection


class ChartColors:
    """Standardized color palette matching railway engineering contracts."""

    # Brand & Primary Palette
    PRIMARY_NAVY = "#1B365D"
    SECONDARY_BLUE = "#2E6B9E"
    ACCENT_TEAL = "#008080"
    SUCCESS_GREEN = "#2E7D32"
    WARNING_AMBER = "#F57C00"
    CRITICAL_RED = "#C62828"

    # Train Roles
    LEADER_TRAIN = "#1565C0"     # Deep Blue
    FOLLOWER_TRAIN = "#D32F2F"   # Vivid Red
    OPPOSING_TRAIN = "#7B1FA2"   # Purple
    NEUTRAL_TRAIN = "#546E7A"    # Slate Gray

    # Speed & Infrastructure Profiles
    SPEED_PROFILE = "#1565C0"
    SPEED_ENVELOPE = "#C62828"   # Dashed permissible line
    GRADIENT_FILL = "#E0E7FF"
    GRADIENT_LINE = "#3F51B5"
    CURVATURE_LINE = "#00897B"

    # Controlling Resources & Bottlenecks
    CONTROLLING_HIGHLIGHT = "#FFCDD2"  # Soft red background fill
    CONTROLLING_BORDER = "#B71C1C"     # Sharp red border

    # Seven Blocking Time Components
    COMPONENT_SETUP = "#90CAF9"               # t1 Light Blue
    COMPONENT_APPROACH = "#FFCC80"            # t2 Light Orange
    COMPONENT_RUNNING = "#A5D6A7"             # t3 Light Green
    COMPONENT_DWELL = "#CE93D8"               # t4 Light Purple
    COMPONENT_GEOMETRIC_CLEARANCE = "#FFF59D" # t5 Light Yellow
    COMPONENT_RESIDUAL_REAR = "#FFAB91"       # t6 Light Coral
    COMPONENT_RELEASE = "#80CBC4"             # t7 Light Teal

    # Surface & Structure
    BG_WHITE = "#FFFFFF"
    BG_LIGHT_GRAY = "#F8F9FA"
    GRID_LIGHT = "#E2E8F0"
    TEXT_DARK = "#1A202C"
    TEXT_MUTED = "#64748B"


COMPONENT_COLOR_MAP = {
    "SETUP": ChartColors.COMPONENT_SETUP,
    "APPROACH": ChartColors.COMPONENT_APPROACH,
    "RUNNING": ChartColors.COMPONENT_RUNNING,
    "DWELL": ChartColors.COMPONENT_DWELL,
    "GEOMETRIC_CLEARANCE": ChartColors.COMPONENT_GEOMETRIC_CLEARANCE,
    "RESIDUAL_REAR": ChartColors.COMPONENT_RESIDUAL_REAR,
    "RELEASE": ChartColors.COMPONENT_RELEASE,
}


def get_plotly_layout(
    title: str,
    xaxis_title: str,
    yaxis_title: str,
    running_direction: Optional[RunningDirection] = None,
    height: int = 600,
    width: Optional[int] = None,
    showlegend: bool = True,
    barmode: Optional[str] = None,
) -> go.Layout:
    """P13-THM-001 to P13-THM-005: Construct standardized professional Plotly layout."""
    annotations = []

    # Direction Annotation Banner (P13-THM-005 & P13-DIR-001)
    if running_direction is not None:
        dir_text = f"Running Direction: {running_direction.value}"
        dir_color = ChartColors.PRIMARY_NAVY if running_direction == RunningDirection.FORWARD else ChartColors.CRITICAL_RED
        annotations.append(
            dict(
                text=f"<b>{dir_text}</b>",
                xref="paper",
                yref="paper",
                x=0.99,
                y=1.05,
                showarrow=False,
                font=dict(size=12, color=dir_color, family="Arial, sans-serif"),
                bgcolor="#EDF2F7",
                bordercolor=dir_color,
                borderwidth=1,
                borderpad=4,
                opacity=0.9,
            )
        )

    layout_kwargs: Dict[str, Any] = dict(
        title=dict(
            text=f"<b>{title}</b>",
            font=dict(size=16, color=ChartColors.PRIMARY_NAVY, family="Arial, sans-serif"),
            x=0.01,
            xanchor="left",
        ),
        xaxis=dict(
            title=dict(text=xaxis_title, font=dict(size=13, color=ChartColors.TEXT_DARK)),
            gridcolor=ChartColors.GRID_LIGHT,
            zerolinecolor=ChartColors.GRID_LIGHT,
            showline=True,
            linecolor=ChartColors.TEXT_MUTED,
            tickfont=dict(size=11, color=ChartColors.TEXT_DARK),
        ),
        yaxis=dict(
            title=dict(text=yaxis_title, font=dict(size=13, color=ChartColors.TEXT_DARK)),
            gridcolor=ChartColors.GRID_LIGHT,
            zerolinecolor=ChartColors.GRID_LIGHT,
            showline=True,
            linecolor=ChartColors.TEXT_MUTED,
            tickfont=dict(size=11, color=ChartColors.TEXT_DARK),
        ),
        plot_bgcolor=ChartColors.BG_WHITE,
        paper_bgcolor=ChartColors.BG_WHITE,
        font=dict(family="Arial, sans-serif", color=ChartColors.TEXT_DARK),
        height=height,
        width=width,
        showlegend=showlegend,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0.0,
            bgcolor="rgba(255, 255, 255, 0.8)",
            bordercolor=ChartColors.GRID_LIGHT,
            borderwidth=1,
        ),
        margin=dict(l=60, r=40, t=80, b=60),
        annotations=annotations,
    )

    if barmode:
        layout_kwargs["barmode"] = barmode

    return go.Layout(**layout_kwargs)


def apply_mpl_theme() -> None:
    """P13-THM-001: Configure Matplotlib default rcParams for engineering publications."""
    mpl.rcParams["figure.facecolor"] = ChartColors.BG_WHITE
    mpl.rcParams["axes.facecolor"] = ChartColors.BG_WHITE
    mpl.rcParams["axes.edgecolor"] = ChartColors.TEXT_MUTED
    mpl.rcParams["axes.labelcolor"] = ChartColors.TEXT_DARK
    mpl.rcParams["axes.titlesize"] = 13
    mpl.rcParams["axes.labelsize"] = 11
    mpl.rcParams["axes.grid"] = True
    mpl.rcParams["grid.color"] = ChartColors.GRID_LIGHT
    mpl.rcParams["grid.linestyle"] = "--"
    mpl.rcParams["grid.alpha"] = 0.7
    mpl.rcParams["xtick.color"] = ChartColors.TEXT_DARK
    mpl.rcParams["ytick.color"] = ChartColors.TEXT_DARK
    mpl.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial", "Helvetica", "sans-serif"]
    mpl.rcParams["font.family"] = "sans-serif"


def setup_mpl_figure(
    figsize: Tuple[float, float] = (10, 6),
    running_direction: Optional[RunningDirection] = None,
    dpi: int = 150,
) -> Tuple[plt.Figure, plt.Axes]:
    """P13-INT-002: Create Matplotlib Figure & Axes with standardized engineering styling."""
    apply_mpl_theme()
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    if running_direction is not None:
        dir_text = f"Running Direction: {running_direction.value}"
        dir_color = ChartColors.PRIMARY_NAVY if running_direction == RunningDirection.FORWARD else ChartColors.CRITICAL_RED
        fig.text(
            0.98,
            0.96,
            dir_text,
            ha="right",
            va="top",
            fontsize=10,
            fontweight="bold",
            color=dir_color,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#EDF2F7", edgecolor=dir_color, alpha=0.9),
        )

    return fig, ax
