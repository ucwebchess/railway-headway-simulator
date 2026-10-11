"""Direction selector component and validation helpers.

Milestone P15 — Mandatory Direction Capability (P15-DIR-001 to P15-DIR-010, P15-DIRV-001 to P15-DIRV-010).
Provides explicit FORWARD / REVERSE direction selection, route compatibility checks,
and direction banner formatting.
"""

from typing import Any, Dict, List, Optional, Tuple
import gradio as gr

from headway.data.canonical import CanonicalProject, TrackDirectionality
from headway.infrastructure.direction import RunningDirection


class DirectionSelector:
    """Manages explicit running direction selection, validation, and presentation."""

    @staticmethod
    def create_component(
        label: str = "Running Direction (Mandatory)",
        elem_id: str = "simulation_running_direction",
        value: str = "FORWARD",
        interactive: bool = True,
    ) -> gr.Radio:
        """P15-DIR-001 & P15-DIR-002: Create explicit FORWARD / REVERSE radio selector."""
        return gr.Radio(
            choices=["FORWARD", "REVERSE"],
            value=value,
            label=label,
            info="Select physical operational train running direction. Determines route resolution, headway, and reporting.",
            interactive=interactive,
            elem_id=elem_id,
        )

    @staticmethod
    def create_explorer_toggle(
        elem_id: str = "explorer_view_direction",
    ) -> gr.Radio:
        """P15-DIR-008: Explorer view-only display orientation toggle (does not affect simulation)."""
        return gr.Radio(
            choices=["FORWARD (Default)", "REVERSE (Inverted)"],
            value="FORWARD (Default)",
            label="Infrastructure Display Orientation",
            info="View-only toggle: orient network schematic and profile from Left-to-Right or Right-to-Left.",
            interactive=True,
            elem_id=elem_id,
        )

    @staticmethod
    def validate_direction(
        direction: RunningDirection,
        project: Optional[CanonicalProject] = None,
        route_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """P15-DIR-004: Validate that the selected direction is compatible with the project and route."""
        if not isinstance(direction, RunningDirection):
            try:
                direction = RunningDirection(str(direction).upper())
            except Exception:
                return False, f"Invalid direction '{direction}'. Must be FORWARD or REVERSE."

        if project is None or not project.infrastructure.track_links:
            # No project loaded yet, syntax is valid
            return True, None

        infra = project.infrastructure

        # If a specific route is requested, check links in route
        if route_id:
            route_links = [lnk for lnk in infra.track_links if lnk.track_id == route_id]
        else:
            route_links = infra.track_links

        if direction == RunningDirection.REVERSE:
            # Check if all tracks are strictly NOMINAL (forward-only)
            nominal_tracks = [
                t.track_id
                for t in infra.tracks
                if getattr(t, "directionality", None) == TrackDirectionality.NOMINAL
            ]
            if len(nominal_tracks) == len(infra.tracks) and len(infra.tracks) > 0:
                return False, (
                    f"Selected corridor does not support REVERSE direction: all tracks are configured as NOMINAL (forward-only). "
                    f"Tracks: {', '.join(nominal_tracks[:5])}"
                )
        elif direction == RunningDirection.FORWARD:
            # Check if all tracks are strictly REVERSE
            reverse_tracks = [
                t.track_id
                for t in infra.tracks
                if getattr(t, "directionality", None) == TrackDirectionality.REVERSE
            ]
            if len(reverse_tracks) == len(infra.tracks) and len(infra.tracks) > 0:
                return False, (
                    f"Selected corridor does not support FORWARD direction: all tracks are configured as REVERSE. "
                    f"Tracks: {', '.join(reverse_tracks[:5])}"
                )

        return True, None

    @staticmethod
    def render_banner(direction: RunningDirection) -> str:
        """P15-DIR-006 & P15-DIR-009: Renders standard high-contrast direction statement banner."""
        dir_val = direction.value if isinstance(direction, RunningDirection) else str(direction).upper()
        bg_color = "#1B365D"  # Navy
        accent_color = "#38BDF8" if dir_val == "FORWARD" else "#F59E0B"
        arrow = "➔" if dir_val == "FORWARD" else "⬅"

        return f"""
        <div style="background-color: {bg_color}; color: #FFFFFF; padding: 10px 18px; border-radius: 6px; font-weight: 700; font-size: 13px; display: flex; align-items: center; justify-content: space-between; margin: 8px 0; border-left: 5px solid {accent_color};">
            <div>
                <span style="color: {accent_color}; margin-right: 8px;">{arrow}</span>
                RUNNING DIRECTION: <span style="letter-spacing: 0.05em; color: #FFFFFF;">{dir_val}</span>
            </div>
            <div style="font-size: 11px; font-weight: 400; color: #94A3B8;">
                { 'Increasing Route Chainage (0 → End)' if dir_val == 'FORWARD' else 'Decreasing Route Chainage (End → 0)' }
            </div>
        </div>
        """
