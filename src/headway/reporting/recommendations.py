"""Rule-based engineering recommendation engine.

Milestone P14 — Professional Engineering Report Generator (RHS-P14-001 § 26 & § 27).
Implements strictly deterministic, evidence-based recommendations derived directly from:
- Governing bottlenecks and pairwise conflicts (P08)
- Residual rear platform track infringements (P07)
- Station platform dwell and allocation constraints (P07, P09)
- Open-line block length constraints (P05, P06, P10)
- TVS ventilation section holding times (P07, P10)
- Junction route locking and sectional release (P07)
- Stochastic operational delay variance (P11)

Invariants:
- P14-REC-003: No unsupported recommendations.
- P14-REC-004: Explicitly flags whether a recommendation has been verified via scenario simulation.
- P14-REC-005: Deterministic engineering rules only; zero unsupported AI-generated claims.
"""

from typing import List, Optional, Sequence
from headway.analysis.conflict_detection import ResourceConflict
from headway.analysis.headway_results import HeadwayResult
from headway.reporting.report_models import (
    BottleneckDiagnosis,
    Recommendation,
    RecommendationCategory,
)
from headway.reporting.result_models import (
    PlatformOccupationRecord,
    SimulationResultPackage,
)


class RecommendationEngine:
    """Evaluates simulation results against formal railway engineering rules to generate actionable recommendations."""

    @classmethod
    def generate_recommendations(
        cls,
        package: SimulationResultPackage,
        headway_result: Optional[HeadwayResult] = None,
        platform_records: Optional[Sequence[PlatformOccupationRecord]] = None,
    ) -> List[Recommendation]:
        """Runs the deterministic rule engine over package results."""
        recommendations: List[Recommendation] = []
        rule_counter = 1

        hw = headway_result
        if not hw and package.headway_results:
            hw = next(iter(package.headway_results.values()))

        # Rule 1: Residual Rear Platform Infringement
        # Check if platform occupation causes residual rear fouling on upstream block
        platforms = platform_records or []
        for plt in platforms:
            if plt.is_residual_rear_active and plt.residual_rear_duration_s > 0.0:
                infringing_blocks = ", ".join(plt.upstream_infringing_resource_ids) or "upstream approach block"
                recommendations.append(
                    Recommendation(
                        recommendation_id=f"REC-{rule_counter:03d}",
                        category=RecommendationCategory.STATION_PLATFORM_MODIFICATION,
                        title=f"Mitigate Residual Rear Fouling at Platform {plt.platform_id}",
                        description=(
                            f"Train dwelling at platform '{plt.platform_id}' ({plt.station_name}) infringes on "
                            f"{infringing_blocks} for {plt.residual_rear_duration_s:.1f} s due to train length exceeding "
                            "the clear platform berth distance."
                        ),
                        rationale=(
                            "Residual rear fouling prevents following trains from approaching the station during passenger dwell, "
                            "artificially inflating the approach component of blocking time."
                        ),
                        expected_benefit=(
                            f"Advancing the stopping marker or relocating the insulated rail joint by {plt.residual_rear_duration_s:.1f} s "
                            "equivalent distance can eliminate upstream block fouling and reduce line headway."
                        ),
                        governing_resource_id=plt.platform_id,
                        requires_further_simulation=True,
                        assumptions_and_limitations=(
                            "Subject to physical platform civil length, signal sight distance, and passenger egress clearances."
                        ),
                    )
                )
                rule_counter += 1
                break  # Generate one high-impact platform rule

        # Rule 2: Open-Line Long Block Bottleneck
        if hw and hw.controlling_conflicts:
            ctrl = hw.controlling_conflicts[0]
            ctrl_type = str(getattr(ctrl, "bottleneck_type", "")).upper()
            res_id = ctrl.leader_resource_id

            if "BLOCK" in ctrl_type or "SIGNAL" in ctrl_type or "TRACK" in ctrl_type:
                dur = ctrl.required_headway_s
                recommendations.append(
                    Recommendation(
                        recommendation_id=f"REC-{rule_counter:03d}",
                        category=RecommendationCategory.SIGNALLING_MODIFICATION,
                        title=f"Subdivide Controlling Signalling Block {res_id}",
                        description=(
                            f"Signalling block resource '{res_id}' governs technical headway with a required headway of {dur:.1f} s. "
                            f"Running and clearing times through this section represent the dominant line constraint."
                        ),
                        rationale=(
                            "Under fixed-block signalling, headway is bounded below by the longest physical block travel time plus setup and release."
                        ),
                        expected_benefit=(
                            "Subdividing this block into two equal sections or upgrading to CBTC moving block can significantly reduce minimum headway."
                        ),
                        governing_resource_id=res_id,
                        requires_further_simulation=True,
                        assumptions_and_limitations=(
                            "Requires verification of train braking distance for multi-aspect braking curves."
                        ),
                    )
                )
                rule_counter += 1

            # Rule 3: Station Dwell Bottleneck
            elif "STATION" in ctrl_type or "PLATFORM" in ctrl_type:
                recommendations.append(
                    Recommendation(
                        recommendation_id=f"REC-{rule_counter:03d}",
                        category=RecommendationCategory.OPERATIONAL_MODIFICATION,
                        title=f"Optimize Platform Dwell Allocation at {res_id}",
                        description=(
                            f"Station platform resource '{res_id}' governs line headway with required headway of {ctrl.required_headway_s:.1f} s. "
                            "Station dwell and berth clearance occupy the platform track continuously."
                        ),
                        rationale=(
                            "Single-platform occupancy creates a hard capacity bottleneck when passenger dwell exceeds running intervals."
                        ),
                        expected_benefit=(
                            "Implementing alternate-platform dispatching or passenger boarding management to reduce dwell variance will expand line capacity."
                        ),
                        governing_resource_id=res_id,
                        requires_further_simulation=True,
                        assumptions_and_limitations=(
                            "Assumes multi-track platform layout is physically feasible."
                        ),
                    )
                )
                rule_counter += 1

            # Rule 4: Junction Interlocking Bottleneck
            elif "JUNCTION" in ctrl_type or "SWITCH" in ctrl_type:
                recommendations.append(
                    Recommendation(
                        recommendation_id=f"REC-{rule_counter:03d}",
                        category=RecommendationCategory.SIGNALLING_MODIFICATION,
                        title=f"Implement Sectional Release at Junction {res_id}",
                        description=(
                            f"Interlocking conflict at junction '{res_id}' imposes a minimum headway of {ctrl.required_headway_s:.1f} s."
                        ),
                        rationale=(
                            "Holding the entire switch ladder locked until complete train exit prolongs route reservation unnecessarily."
                        ),
                        expected_benefit=(
                            "Sectional track release will free trailing points as soon as rear train clearance is achieved, reducing conflicting headway."
                        ),
                        governing_resource_id=res_id,
                        requires_further_simulation=True,
                        assumptions_and_limitations="Requires track circuit / axle counter positioning at switch fouling points.",
                    )
                )
                rule_counter += 1

        # Rule 5: TVS Tunnel Ventilation Constraint
        # Check if TVS restrictions are active and create constraint
        tvs_events = package.metadata.get("tvs_events") or package.metadata.get("tvs_occupations") or []
        if tvs_events:
            def _get_tvs_dur(e):
                if isinstance(e, dict):
                    return float(e.get("exit_time_s", 0.0) or e.get("cleared_time_s", 0.0)) - float(e.get("entry_time_s", 0.0) or e.get("entered_time_s", 0.0))
                return getattr(e, "cleared_time_s", 0.0) - getattr(e, "entered_time_s", 0.0)

            def _get_tvs_id(e):
                if isinstance(e, dict):
                    return e.get("tvs_id") or e.get("tvs_zone_id") or "TVS_ZONE"
                return getattr(e, "tvs_zone_id", getattr(e, "tvs_id", "TVS_ZONE"))

            longest_tvs = max(tvs_events, key=_get_tvs_dur, default=None)
            if longest_tvs:
                tvs_dur = _get_tvs_dur(longest_tvs)
                zone_id = _get_tvs_id(longest_tvs)
                if hw and tvs_dur > (hw.headway_s * 0.75):
                    recommendations.append(
                        Recommendation(
                            recommendation_id=f"REC-{rule_counter:03d}",
                            category=RecommendationCategory.TVS_OPERATIONAL_STRATEGY,
                            title=f"Review Tunnel Ventilation Staging in Zone {zone_id}",
                            description=(
                                f"TVS ventilation section '{zone_id}' enforces single-train occupancy for {tvs_dur:.1f} s. "
                                "This duration approaches or exceeds signalling headway, making tunnel safety rules governing for line capacity."
                            ),
                            rationale=(
                                "Mandatory emergency smoke extraction boundaries prevent entry of a follower train until the leader has cleared the entire TVS section."
                            ),
                            expected_benefit=(
                                "Subdividing long tunnel sections or optimizing ventilation damper activation delay will mitigate TVS-induced train holding."
                            ),
                            governing_resource_id=zone_id,
                            requires_further_simulation=True,
                            assumptions_and_limitations="Requires aerodynamic and emergency egress fire-life safety verification.",
                        )
                    )
                    rule_counter += 1

        # Rule 6: Stochastic Operational Delay Buffering
        stoch_summaries = (
            list(package.monte_carlo_result.summaries.values())
            if (package.monte_carlo_result and package.monte_carlo_result.summaries)
            else package.metadata.get("stochastic_summaries", [])
        )
        if stoch_summaries:
            headway_stat = next((s for s in stoch_summaries if "headway" in s.metric_name.lower()), None)
            if headway_stat and headway_stat.p95 > headway_stat.mean * 1.15:
                recommendations.append(
                    Recommendation(
                        recommendation_id=f"REC-{rule_counter:03d}",
                        category=RecommendationCategory.OPERATIONAL_MODIFICATION,
                        title="Incorporate P95 Headway Margin into Operational Timetable",
                        description=(
                            f"Simulated headway displays high operational variability: deterministic mean is {headway_stat.mean:.1f} s, "
                            f"whereas 95th percentile reaches {headway_stat.p95:.1f} s (a spread of {headway_stat.p95 - headway_stat.mean:.1f} s)."
                        ),
                        rationale=(
                            "Dispatching trains strictly at the deterministic minimum will lead to rapid delay propagation under stochastic dwell jitter."
                        ),
                        expected_benefit=(
                            f"Scheduling trains with a dispatch headway of at least {headway_stat.p95:.1f} s will provide 95% punctuality resilience."
                        ),
                        requires_further_simulation=False,
                        assumptions_and_limitations="Reflects configured dwell and traction variation profiles.",
                    )
                )
                rule_counter += 1

        return recommendations
