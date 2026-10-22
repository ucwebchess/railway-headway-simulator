"""Session state management for the Railway Headway Simulator UI.

Milestone P15 — Session State Management (P15-STATE-001 to P15-STATE-005).
Preserves project, scenario, and simulation results throughout the active Gradio session.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from headway.data.canonical import CanonicalProject
from headway.data.validation import ValidationReport
from headway.infrastructure.direction import RunningDirection
from headway.reporting.report_models import ReportDocument
from headway.reporting.result_models import SimulationResultPackage
from headway.scenarios.scenario_manager import ScenarioManager
from headway.ui.file_manager import FileManager


@dataclass
class AppState:
    """Manages active session data, loaded models, and simulation outputs."""

    # Project and Data
    current_project: Optional[CanonicalProject] = None
    project_name: str = "No Project Loaded"
    project_id: str = "NONE"
    validation_report: Optional[ValidationReport] = None
    source_files: Dict[str, Path] = field(default_factory=dict)

    # Scenarios
    scenario_manager: Optional[ScenarioManager] = None
    active_scenario_id: str = "BASELINE"

    # Simulation Controls & Results
    selected_running_direction: RunningDirection = RunningDirection.FORWARD
    simulation_packages: Dict[str, SimulationResultPackage] = field(default_factory=dict)
    latest_result_package: Optional[SimulationResultPackage] = None
    latest_report_doc: Optional[ReportDocument] = None
    report_config: Optional[Any] = None
    reports_dir: Path = field(default_factory=lambda: Path(os.environ.get("HEADWAY_STORAGE_DIR", Path.cwd() / "storage")) / "reports")
    analysis_pf_map: Dict[str, float] = field(default_factory=dict)

    # Numerical & Operational Parameters (DEF-15)
    dt_s: float = 1.0
    max_duration_s: float = 7200.0
    planning_margin_s: float = 18.0
    monte_carlo_reps: int = 100

    # Logging and Diagnostics
    session_logs: List[str] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def project(self) -> Optional[CanonicalProject]:
        """Convenience property for current_project."""
        return self.current_project

    @property
    def scenarios(self) -> Dict[str, Any]:
        """Returns map of scenario IDs to ScenarioDefinition."""
        if not self.scenario_manager:
            return {}
        return {s.scenario_id: s for s in self.scenario_manager.list_scenarios()}

    def reset(self) -> None:
        """Resets the application session state to a clean initial state."""
        self.current_project = None
        self.project_name = "No Project Loaded"
        self.project_id = "NONE"
        self.validation_report = None
        self.source_files.clear()
        self.scenario_manager = None
        self.active_scenario_id = "BASELINE"
        self.selected_running_direction = RunningDirection.FORWARD
        self.simulation_packages.clear()
        self.latest_result_package = None
        self.latest_report_doc = None
        self.report_config = None
        self.analysis_pf_map.clear()
        self.dt_s = 1.0
        self.max_duration_s = 7200.0
        self.planning_margin_s = 18.0
        self.monte_carlo_reps = 100
        self.session_logs = [f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Session reset."]
        self.last_updated = datetime.now(timezone.utc).isoformat()

    def set_project(
        self,
        project: CanonicalProject,
        validation_report: Optional[ValidationReport] = None,
        source_files: Optional[Dict[str, Path]] = None,
    ) -> None:
        """Loads a new canonical project into session state and initializes scenarios."""
        # Clear previous simulation runs, reports, and packages to prevent UI state leakage
        self.simulation_packages.clear()
        self.latest_result_package = None
        self.latest_report_doc = None
        self.analysis_pf_map.clear()
        self.active_scenario_id = "BASELINE"

        self.current_project = project
        self.project_name = project.name or project.project_id
        self.project_id = project.project_id
        self.validation_report = validation_report
        self.source_files = source_files or {}

        # Initialize scenario manager from project
        try:
            self.scenario_manager = ScenarioManager(project)
            self.active_scenario_id = "BASELINE"
            existing_ids = {s.scenario_id for s in self.scenario_manager.list_scenarios()}
            for sc in project.scenarios:
                if sc.scenario_id not in existing_ids and not sc.is_baseline:
                    try:
                        self.scenario_manager.create_scenario(
                            scenario_id=sc.scenario_id,
                            scenario_name=sc.scenario_id,
                            description=sc.description or "",
                            base_scenario_id="BASELINE",
                        )
                    except Exception:
                        pass
        except Exception:
            self.scenario_manager = None

        # Populate analysis performance factor map (DEF-10)
        self.update_analysis_pf_map()

        self.last_updated = datetime.now(timezone.utc).isoformat()
        self.session_logs.append(
            f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Loaded project '{self.project_name}' ({self.project_id})."
        )

    def update_analysis_pf_map(self) -> Dict[str, float]:
        """Populates analysis_pf_map from current_project.analysis.analyses."""
        self.analysis_pf_map = {}
        if self.current_project and getattr(self.current_project, "analysis", None) and getattr(self.current_project.analysis, "analyses", None):
            for an in self.current_project.analysis.analyses:
                label = f"{an.analysis_id} (PF: {float(an.performance_factor):.2f})"
                self.analysis_pf_map[label] = float(an.performance_factor)
        return self.analysis_pf_map

    def get_analysis_choices(self) -> Tuple[List[str], Dict[str, float], str, float]:
        """Returns dropdown choices, mapping dict, default choice, and default PF."""
        self.update_analysis_pf_map()
        if self.analysis_pf_map:
            choices = list(self.analysis_pf_map.keys())
            return choices, dict(self.analysis_pf_map), choices[0], self.analysis_pf_map[choices[0]]
        default_label = "AN_DEFAULT (PF: 1.00)"
        return [default_label], {default_label: 1.00}, default_label, 1.00

    def load_example(self, example_name: str) -> Tuple[bool, str]:
        """Loads an official example project."""
        try:
            project, report, files = FileManager.load_example_project(example_name)
            self.set_project(project, validation_report=report, source_files=files)
            return True, f"Example project '{example_name}' loaded successfully."
        except Exception as e:
            return False, f"Failed to load example '{example_name}': {e}"

    def is_simulation_ready(self) -> bool:
        """True if project data has been validated and is ready for simulation."""
        if self.current_project is None:
            return False
        if self.validation_report is not None:
            return self.validation_report.is_simulation_ready
        return True

    def create_scenario(
        self,
        scenario_id: str,
        parent_scenario_id: Optional[str] = "BASELINE",
        description: str = "",
        scenario_name: Optional[str] = None,
    ) -> Any:
        """Branches a new scenario from an existing parent."""
        if not self.scenario_manager:
            raise ValueError("No active project loaded to branch scenarios.")
        name = scenario_name or scenario_id
        sc_def = self.scenario_manager.create_scenario(
            scenario_id=scenario_id,
            scenario_name=name,
            description=description,
            base_scenario_id=parent_scenario_id,
        )
        if self.current_project:
            from headway.data.canonical import Scenario
            if not any(s.scenario_id == scenario_id for s in self.current_project.scenarios):
                self.current_project.scenarios.append(
                    Scenario(
                        scenario_id=scenario_id,
                        description=description or name,
                        is_baseline=False,
                        overrides=[],
                    )
                )
        return sc_def

    def delete_scenario(self, scenario_id: str) -> bool:
        """Deletes a scenario by ID, enforcing baseline protection."""
        if scenario_id == "BASELINE":
            raise ValueError("Cannot delete the immutable baseline scenario.")
        if not self.scenario_manager:
            raise ValueError("No active scenario manager.")
        return self.scenario_manager.delete_scenario(scenario_id)

    def get_project_summary_stats(self) -> Dict[str, Any]:
        """Returns high-level statistics summary of project elements."""
        if not self.current_project:
            return {"total_tracks": 0, "total_track_links": 0, "total_signals": 0, "total_stations": 0}
        infra = self.current_project.infrastructure
        return {
            "total_tracks": len(infra.tracks),
            "total_track_links": len(infra.track_links),
            "total_signals": len(self.current_project.signalling.signals),
            "total_stations": len(infra.stations),
        }

    def get_project_statistics(self) -> Dict[str, Any]:
        """Returns structured statistics of the loaded project."""
        if not self.current_project:
            return {
                "Route Length (km)": "0.0",
                "Tracks": "0",
                "Track Links": "0",
                "Signalling Blocks": "0",
                "Signals": "0",
                "Stations": "0",
                "Platforms": "0",
                "Tunnels": "0",
                "TVS Sections": "0",
                "Train Types": "0",
                "Service Patterns": "0",
                "Scenarios": "0",
            }

        infra = self.current_project.infrastructure
        rs = self.current_project.rolling_stock
        ops = self.current_project.operations
        scns = self.current_project.scenarios

        total_length_km = sum(lnk.length_m for lnk in infra.track_links) / 1000.0

        return {
            "Route Length (km)": f"{total_length_km:.2f}",
            "Tracks": str(len(infra.tracks)),
            "Track Links": str(len(infra.track_links)),
            "Signalling Blocks": str(len(self.current_project.signalling.blocks)),
            "Signals": str(len(self.current_project.signalling.signals)),
            "Stations": str(len(infra.stations)),
            "Platforms": str(len(infra.platforms)),
            "Tunnels": str(len(infra.tunnels)),
            "TVS Sections": str(len(infra.tvs_sections)),
            "Train Types": str(len(rs.train_types)),
            "Service Patterns": str(len(ops.service_patterns)),
            "Scenarios": str(len(self.scenario_manager.get_all_scenarios()) if self.scenario_manager else len(scns)),
        }

    def get_dataset_status(self) -> Dict[str, str]:
        """Returns readiness status for all six datasets."""
        if not self.current_project:
            return {
                "Infrastructure": "Not Loaded",
                "Signalling": "Not Loaded",
                "Rolling Stock": "Not Loaded",
                "Operations": "Not Loaded",
                "Headway Analysis": "Not Loaded",
                "Scenarios": "Not Loaded",
                "Validation Status": "No Data",
                "Simulation Ready": "No",
            }

        ready = bool(self.validation_report and self.validation_report.is_simulation_ready)
        has_errors = bool(self.validation_report and self.validation_report.has_errors)
        val_status = "Errors Detected" if has_errors else ("Simulation Ready" if ready else "Validated with Warnings")

        scn_count = len(self.scenario_manager.get_all_scenarios()) if self.scenario_manager else (len(self.current_project.scenarios) if self.current_project else 1)
        return {
            "Infrastructure": f"Loaded ({len(self.current_project.infrastructure.track_links)} links)",
            "Signalling": f"Loaded ({len(self.current_project.signalling.blocks)} blocks)",
            "Rolling Stock": f"Loaded ({len(self.current_project.rolling_stock.train_types)} trains)",
            "Operations": f"Loaded ({len(self.current_project.operations.service_patterns)} services)",
            "Headway Analysis": "Configured",
            "Scenarios": f"Configured ({scn_count})",
            "Validation Status": val_status,
            "Simulation Ready": "Yes" if ready else "No",
        }

    def get_latest_kpis(self) -> Dict[str, str]:
        """Returns headline KPIs from the most recent simulation run."""
        if not self.latest_result_package or not self.latest_report_doc:
            return {
                "Technical Headway": "Not Available",
                "Theoretical Capacity": "Not Available",
                "Planning Capacity": "Not Available",
                "Controlling Bottleneck": "Not Available",
                "Running Direction": self.selected_running_direction.value,
            }

        kpis = self.latest_report_doc.executive_kpis
        return {
            "Technical Headway": f"{kpis.technical_headway_s:.1f} s ({kpis.technical_headway_min:.2f} min)",
            "Theoretical Capacity": f"{kpis.theoretical_capacity_tph:.1f} tph",
            "Planning Capacity": f"{kpis.planning_capacity_tph:.1f} tph",
            "Planning Margin": f"Margin: {kpis.planning_margin_s:.0f} s",
            "Performance Factor": kpis.performance_factor_str,
            "Controlling Bottleneck": f"{kpis.controlling_bottleneck_id} ({kpis.controlling_bottleneck_type})",
            "Running Direction": self.latest_result_package.running_direction.value,
        }

    def set_latest_results(
        self,
        package: SimulationResultPackage,
        doc: ReportDocument,
    ) -> None:
        """Stores the latest simulation package and report document."""
        self.latest_result_package = package
        self.latest_report_doc = doc
        self.simulation_packages[package.running_direction.value] = package
        self.last_updated = datetime.now(timezone.utc).isoformat()
        self.session_logs.append(
            f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Simulation completed in direction {package.running_direction.value} (Headway: {doc.executive_kpis.technical_headway_s:.1f}s)."
        )

    def export_project_zip(self, output_zip_path: Path) -> Path:
        """Exports the active session project state as a ZIP package."""
        if not self.current_project:
            raise ValueError("No project loaded to export.")
        from headway.data.package import ProjectPackage

        return ProjectPackage.export_package(
            project=self.current_project,
            output_zip_path=output_zip_path,
            excel_workbooks=self.source_files,
            validation_report=self.validation_report,
        )

    def import_project_zip(self, input_zip_path: Path) -> None:
        """Imports and restores a project package from ZIP."""
        from headway.ui.file_manager import ProjectFileManager

        proj, manifest, files, report = ProjectFileManager.import_project_zip(input_zip_path)
        self.set_project(proj, validation_report=report, source_files=files)


# Global session state container
session_state = AppState()
