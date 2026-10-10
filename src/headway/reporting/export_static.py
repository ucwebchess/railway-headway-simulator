"""Static figure rendering and export engine.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 25).
Satisfies:
- P13-INT-001: Interactive Plotly figures for future Gradio integration.
- P13-INT-002: Static high-resolution export (PNG, SVG, PDF) for professional reports (P14).
- P13-INT-003: Reusable, deterministic figure rendering across platforms.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Union
import matplotlib.pyplot as plt
import plotly.graph_objects as go

from headway.reporting.chart_theme import apply_mpl_theme


class StaticFigureExporter:
    """Handles static export of Plotly and Matplotlib figures to disk."""

    @classmethod
    def export_plotly_to_html(
        cls,
        fig: go.Figure,
        filepath: Union[str, Path],
        include_plotlyjs: Union[bool, str] = "cdn",
    ) -> str:
        """Export interactive Plotly figure to standalone HTML file."""
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(str(p), include_plotlyjs=include_plotlyjs, full_html=True)
        return str(p)

    @classmethod
    def export_plotly_to_json(
        cls,
        fig: go.Figure,
        filepath: Optional[Union[str, Path]] = None,
    ) -> str:
        """Export Plotly figure specification to JSON string or file."""
        json_str = fig.to_json()
        if filepath:
            p = Path(filepath)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json_str, encoding="utf-8")
        return json_str

    @classmethod
    def export_matplotlib_figure(
        cls,
        fig: plt.Figure,
        filepath: Union[str, Path],
        dpi: int = 300,
    ) -> str:
        """Export Matplotlib figure to publication-quality PNG, SVG, or PDF."""
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(p), dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
        return str(p)

    @classmethod
    def export_figure_to_image(
        cls,
        fig: Union[go.Figure, plt.Figure],
        filepath: Union[str, Path],
        dpi: int = 300,
        width: int = 1200,
        height: int = 700,
    ) -> str:
        """Universal export method supporting both Plotly and Matplotlib with automatic fallback."""
        p = Path(filepath)
        ext = p.suffix.lower()
        if ext not in (".png", ".svg", ".pdf", ".jpg", ".jpeg"):
            raise ValueError(f"Unsupported static export format '{ext}'. Must be .png, .svg, .pdf, or .jpg.")
        if width <= 0 or height <= 0:
            raise ValueError(f"Export dimensions must be positive, got {width}x{height}.")
        if dpi <= 0:
            raise ValueError(f"DPI must be positive, got {dpi}.")

        p.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(fig, plt.Figure):
            return cls.export_matplotlib_figure(fig, p, dpi=dpi)

        # Plotly figure: attempt write_image, fallback to matplotlib renderer if kaleido/chrome absent
        if isinstance(fig, go.Figure):
            try:
                fig.write_image(str(p), width=width, height=height, scale=2)
                return str(p)
            except Exception:
                # Render equivalent static figure via matplotlib fallback
                return cls._fallback_plotly_to_matplotlib(fig, p, dpi=dpi)

        raise TypeError(f"Unsupported figure type: {type(fig).__name__}")

    @classmethod
    def _fallback_plotly_to_matplotlib(
        cls,
        plotly_fig: go.Figure,
        filepath: Path,
        dpi: int = 150,
    ) -> str:
        """Converts traces and layout from Plotly figure to Matplotlib figure and saves image."""
        apply_mpl_theme()
        mpl_fig, ax = plt.subplots(figsize=(10, 6), dpi=dpi)

        title_text = ""
        if plotly_fig.layout.title and hasattr(plotly_fig.layout.title, "text"):
            # Strip simple HTML bold tags
            title_text = plotly_fig.layout.title.text.replace("<b>", "").replace("</b>", "")

        for trace in plotly_fig.data:
            x_data = getattr(trace, "x", None)
            y_data = getattr(trace, "y", None)
            name = getattr(trace, "name", "")
            trace_type = trace.type

            if x_data is not None and y_data is not None:
                if trace_type in ("scatter", "scattergl"):
                    mode = getattr(trace, "mode", "lines")
                    if "lines" in mode and "markers" in mode:
                        ax.plot(x_data, y_data, marker="o", label=name)
                    elif "markers" in mode:
                        ax.scatter(x_data, y_data, label=name)
                    else:
                        ax.plot(x_data, y_data, label=name)
                elif trace_type == "bar":
                    orientation = getattr(trace, "orientation", "v")
                    base = getattr(trace, "base", None)
                    if orientation == "h":
                        ax.barh(y_data, x_data, left=base, label=name, alpha=0.8)
                    else:
                        ax.bar(x_data, y_data, bottom=base, label=name, alpha=0.8)
                elif trace_type == "histogram":
                    ax.hist(x_data, bins=30, label=name, alpha=0.7)

        if title_text:
            ax.set_title(title_text, fontsize=12, fontweight="bold", color="#1B365D", loc="left")

        if plotly_fig.layout.xaxis and plotly_fig.layout.xaxis.title:
            x_title = getattr(plotly_fig.layout.xaxis.title, "text", "")
            if x_title:
                ax.set_xlabel(x_title)

        if plotly_fig.layout.yaxis and plotly_fig.layout.yaxis.title:
            y_title = getattr(plotly_fig.layout.yaxis.title, "text", "")
            if y_title:
                ax.set_ylabel(y_title)

        handles, labels = ax.get_legend_handles_labels()
        if handles and plotly_fig.layout.showlegend is not False:
            ax.legend(loc="best", fontsize=9)

        mpl_fig.tight_layout()
        mpl_fig.savefig(str(filepath), dpi=dpi, bbox_inches="tight")
        plt.close(mpl_fig)
        return str(filepath)


def export_figure_headless(
    fig: Union[go.Figure, plt.Figure],
    filepath: Union[str, Path],
    dpi: int = 300,
    width: int = 1200,
    height: int = 700,
) -> str:
    """Convenience functional wrapper for StaticFigureExporter.export_figure_to_image."""
    return StaticFigureExporter.export_figure_to_image(
        fig=fig, filepath=filepath, dpi=dpi, width=width, height=height
    )


def export_matplotlib_figure(
    fig: plt.Figure,
    filepath: Union[str, Path],
    dpi: int = 300,
) -> str:
    """Convenience functional wrapper for StaticFigureExporter.export_matplotlib_figure."""
    return StaticFigureExporter.export_matplotlib_figure(
        fig=fig, filepath=filepath, dpi=dpi
    )
