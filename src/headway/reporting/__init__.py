"""Engineering reporting, export, and visualization subsystem.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001).
Covers:
- Standardized simulation result objects and packages.
- Result validation and structured diagnostics.
- Chart themes, color standards, and layout builders.
- Visualization data adapters with strict direction handling.
- Speed-distance, gradient, curvature, and track alignment profiles.
- Blocking-time stairway diagrams and seven-component stacked charts.
- Time-distance diagrams and mixed-traffic headway heatmaps.
- Station and platform occupation diagrams.
- TVS ventilation section occupation and comparison diagrams.
- Block-length sensitivity and capacity saturation curves.
- Stochastic distribution histograms, CDFs, box plots, and reliability curves.
- Scenario comparison and bottleneck migration visualizations.
- Standardized engineering tables (conflicts, occupations, timings, provenance).
- Static figure export for future PDF reports (P14).
"""

from headway.reporting.chart_theme import (
    COMPONENT_COLOR_MAP,
    ChartColors,
    apply_mpl_theme,
    get_plotly_layout,
    setup_mpl_figure,
)
from headway.reporting.charts_blocking import (
    create_blocking_stairway_figure,
    create_seven_component_figure,
)
from headway.reporting.charts_capacity import (
    create_block_sensitivity_figure,
    create_capacity_comparison_figure,
    create_capacity_saturation_figure,
)
from headway.reporting.charts_headway import (
    create_mixed_traffic_heatmap,
    create_time_distance_figure,
)
from headway.reporting.charts_scenario import (
    create_bottleneck_migration_figure,
    create_scenario_kpi_comparison_figure,
)
from headway.reporting.charts_speed import (
    create_curvature_profile_figure,
    create_gradient_profile_figure,
    create_speed_distance_figure,
    create_track_alignment_combined_figure,
)
from headway.reporting.charts_station import create_platform_occupation_figure
from headway.reporting.charts_stochastic import (
    create_confidence_interval_figure,
    create_reliability_curve_figure,
    create_stochastic_box_plot,
    create_stochastic_cdf_figure,
    create_stochastic_histogram_figure,
)
from headway.reporting.charts_tvs import (
    create_tvs_comparison_figure,
    create_tvs_occupation_figure,
)
from headway.reporting.export_static import (
    StaticFigureExporter,
    export_figure_headless,
    export_matplotlib_figure,
)
from headway.reporting.result_models import (
    ConflictRankingRecord,
    PlatformOccupationRecord,
    ResourceProvenanceRecord,
    ResourceTimingRecord,
    SimulationResultPackage,
    StationStopRecord,
)
from headway.reporting.result_validation import (
    DiagnosticCode,
    ResultDiagnostic,
    ResultValidationReport,
    ResultValidator,
)
from headway.reporting.tables import (
    EngineeringTable,
    create_conflict_ranking_table,
    create_headway_matrix_table,
    create_longest_occupation_table,
    create_resource_provenance_table,
    create_resource_timing_table,
    create_scenario_comparison_table,
    create_station_stopping_table,
    export_table,
)
from headway.reporting.visualization_adapters import VisualizationAdapter

__all__ = [
    # Result Models & Validation
    "SimulationResultPackage",
    "PlatformOccupationRecord",
    "StationStopRecord",
    "ConflictRankingRecord",
    "ResourceTimingRecord",
    "ResourceProvenanceRecord",
    "DiagnosticCode",
    "ResultDiagnostic",
    "ResultValidationReport",
    "ResultValidator",
    # Theme & Styling
    "ChartColors",
    "COMPONENT_COLOR_MAP",
    "get_plotly_layout",
    "apply_mpl_theme",
    "setup_mpl_figure",
    # Adapters
    "VisualizationAdapter",
    # Chart Generators
    "create_speed_distance_figure",
    "create_gradient_profile_figure",
    "create_curvature_profile_figure",
    "create_track_alignment_combined_figure",
    "create_blocking_stairway_figure",
    "create_seven_component_figure",
    "create_time_distance_figure",
    "create_mixed_traffic_heatmap",
    "create_platform_occupation_figure",
    "create_tvs_occupation_figure",
    "create_tvs_comparison_figure",
    "create_block_sensitivity_figure",
    "create_capacity_saturation_figure",
    "create_capacity_comparison_figure",
    "create_stochastic_histogram_figure",
    "create_stochastic_cdf_figure",
    "create_stochastic_box_plot",
    "create_confidence_interval_figure",
    "create_reliability_curve_figure",
    "create_scenario_kpi_comparison_figure",
    "create_bottleneck_migration_figure",
    # Tables & Export
    "EngineeringTable",
    "create_conflict_ranking_table",
    "create_longest_occupation_table",
    "create_station_stopping_table",
    "create_resource_timing_table",
    "create_resource_provenance_table",
    "create_headway_matrix_table",
    "create_scenario_comparison_table",
    "export_table",
    "StaticFigureExporter",
    "export_figure_headless",
    "export_matplotlib_figure",
]
