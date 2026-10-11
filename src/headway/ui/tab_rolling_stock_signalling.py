"""Tab 5: Rolling Stock & Signalling for Railway Headway Simulator.

Milestone P15 — UI Integration (P15-TAB-005).
"""

from typing import Any, Dict, List, Optional, Tuple
import gradio as gr
import numpy as np
import plotly.graph_objects as go

from headway.reporting.chart_theme import ChartColors, apply_plotly_theme
from headway.ui.state import session_state


def create_rolling_stock_signalling_tab() -> Dict[str, Any]:
    """Constructs Tab 5: Rolling Stock & Signalling components and event bindings."""
    components = {}

    with gr.Column():
        gr.Markdown("### Rolling Stock Physics & Signalling Architecture Inspector")
        gr.Markdown(
            "Examine microscopic train dynamic characteristics (traction curves, Davis aerodynamic drag, "
            "service/emergency braking profiles) and signalling technologies (Fixed-Block, ETCS Level 2, CBTC)."
        )

        with gr.Row():
            components["train_selector"] = gr.Dropdown(
                choices=[],
                value=None,
                label="Select Rolling Stock Model",
                info="Choose from train types registered in the active project.",
                scale=2,
            )
            components["btn_refresh_rs"] = gr.Button("🔄 Inspect Rolling Stock & Signalling", variant="primary", scale=1)

        # Specifications Card
        components["rs_spec_card"] = gr.HTML("<div style='color: #64748B;'>Select a train model to inspect.</div>")

        # Visualizations Row
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("#### Tractive Effort Curve")
                components["plot_traction"] = gr.Plot(label="Traction vs Speed")
            with gr.Column(scale=1):
                gr.Markdown("#### Davis Aerodynamic Resistance")
                components["plot_davis"] = gr.Plot(label="Davis Resistance vs Speed")

        # Signalling Architecture Section
        gr.Markdown("---")
        gr.Markdown("#### Signalling System & Aspect Progression")

        with gr.Row():
            with gr.Column(scale=1):
                components["signalling_info_card"] = gr.HTML(
                    """
                    <div class="kpi-card">
                        <div class="kpi-title">Signalling Configuration</div>
                        <div style="font-size: 16px; font-weight: 700; color: #1B365D;">Not Loaded</div>
                        <div style="font-size: 12px; color: #64748B; margin-top: 4px;">Aspect Model: - | Technology: -</div>
                    </div>
                    """
                )
            with gr.Column(scale=1):
                components["fidelity_info_card"] = gr.HTML(
                    """
                    <div class="kpi-card">
                        <div class="kpi-title">Signalling Model Fidelity</div>
                        <div style="font-size: 16px; font-weight: 700; color: #00828A;">MICROSCOPIC_HIGH_FIDELITY</div>
                        <div style="font-size: 12px; color: #64748B; margin-top: 4px;">Dynamic aspect progression, overlap clearing & route locking</div>
                    </div>
                    """
                )

        components["tbl_signals"] = gr.Dataframe(
            headers=["Signal ID", "Link ID", "Position (m)", "Signal Type", "Aspect Model", "Approach Locking (s)"],
            value=[],
            interactive=False,
            label="Signals & Aspect Configuration",
        )

    def update_rs_view(selected_tt_id: Optional[str]) -> Tuple[Any, str, go.Figure, go.Figure, str, List[List[Any]]]:
        proj = session_state.current_project
        fig_tr = go.Figure()
        fig_dv = go.Figure()

        if not proj or not proj.rolling_stock.train_types:
            fig_tr.add_annotation(text="No Rolling Stock Loaded", showarrow=False)
            fig_dv.add_annotation(text="No Rolling Stock Loaded", showarrow=False)
            card = "<div style='color: #64748B;'>No train types available. Load a project first.</div>"
            sig_card = "<div style='color: #64748B;'>No signalling configuration available.</div>"
            return gr.update(choices=[]), card, fig_tr, fig_dv, sig_card, []

        tt_list = list(proj.rolling_stock.train_types)
        tt_names = [tt.train_type_id for tt in tt_list]

        cur_tt = next((tt for tt in tt_list if tt.train_type_id == selected_tt_id), tt_list[0])
        max_v = cur_tt.max_speed_ms * 3.6
        speeds_kmh = np.linspace(0, max_v, 50)
        speeds_ms = speeds_kmh / 3.6

        # Traction curve: F = min(F_max, P / v)
        p_watts = cur_tt.power_w if cur_tt.power_w is not None else 2_400_000.0
        f_max = cur_tt.max_tractive_effort_n if cur_tt.max_tractive_effort_n is not None else 280_000.0
        forces_kn = []
        for v in speeds_ms:
            if v <= 0.5:
                forces_kn.append(f_max / 1000.0)
            else:
                forces_kn.append(min(f_max, p_watts / v) / 1000.0)

        fig_tr.add_trace(go.Scatter(
            x=speeds_kmh,
            y=forces_kn,
            mode="lines",
            line=dict(color=ChartColors.PRIMARY_NAVY, width=3),
            name="Tractive Effort (kN)",
        ))
        fig_tr.update_layout(
            title=f"Tractive Effort vs Speed [{cur_tt.train_type_id}]",
            xaxis_title="Speed (km/h)",
            yaxis_title="Tractive Force (kN)",
            height=280,
            margin=dict(l=50, r=30, t=40, b=40),
        )
        apply_plotly_theme(fig_tr)

        # Davis resistance: R = A + Bv + Cv^2
        a = cur_tt.davis_a_n
        b = cur_tt.davis_b_ns_m
        c = cur_tt.davis_c_ns2_m2
        davis_kn = [(a + b * v + c * (v ** 2)) / 1000.0 for v in speeds_ms]

        fig_dv.add_trace(go.Scatter(
            x=speeds_kmh,
            y=davis_kn,
            mode="lines",
            line=dict(color=ChartColors.CRITICAL_RED, width=3),
            name="Davis Resistance (kN)",
        ))
        fig_dv.update_layout(
            title="Aerodynamic & Mechanical Davis Resistance",
            xaxis_title="Speed (km/h)",
            yaxis_title="Total Resistance (kN)",
            height=280,
            margin=dict(l=50, r=30, t=40, b=40),
        )
        apply_plotly_theme(fig_dv)

        tare_t = cur_tt.mass_empty_kg / 1000.0
        gross_t = cur_tt.mass_loaded_kg / 1000.0
        dec_svc = cur_tt.max_service_deceleration_ms2
        dec_emg = cur_tt.emergency_deceleration_ms2
        p_kw = p_watts / 1000.0
        f_max_kn = f_max / 1000.0

        spec_card = f"""
        <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 16px; margin: 8px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="font-weight: 700; color: #1B365D; font-size: 16px; margin-bottom: 8px;">
                🚄 {getattr(cur_tt, 'description', None) or cur_tt.train_type_id} — Technical Specifications
            </div>
            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; font-size: 13px;">
                <div><span style="color: #64748B;">Train Length:</span> <strong>{cur_tt.length_m:.1f} m</strong></div>
                <div><span style="color: #64748B;">Tare Mass:</span> <strong>{tare_t:.1f} t</strong></div>
                <div><span style="color: #64748B;">Gross Mass:</span> <strong>{gross_t:.1f} t</strong></div>
                <div><span style="color: #64748B;">Max Design Speed:</span> <strong>{max_v:.0f} km/h</strong></div>
                <div><span style="color: #64748B;">Service Braking:</span> <strong>{dec_svc:.2f} m/s²</strong></div>
                <div><span style="color: #64748B;">Emergency Braking:</span> <strong>{dec_emg:.2f} m/s²</strong></div>
                <div><span style="color: #64748B;">Continuous Power:</span> <strong>{p_kw:.0f} kW</strong></div>
                <div><span style="color: #64748B;">Max Tractive Effort:</span> <strong>{f_max_kn:.1f} kN</strong></div>
            </div>
        </div>
        """

        sig = proj.signalling
        sig_sys = getattr(sig, "system", None)
        tech_name = sig_sys.technology_type.value if (sig_sys and hasattr(sig_sys.technology_type, "value")) else "FIXED_BLOCK_3ASPECT"
        aspect_model = sig_sys.aspect_model.value if (sig_sys and hasattr(sig_sys.aspect_model, "value")) else "THREE_ASPECT"

        sig_card = f"""
        <div class="kpi-card" style="border-left: 5px solid #1B365D;">
            <div class="kpi-title">Active Signalling System</div>
            <div style="font-size: 16px; font-weight: 700; color: #1B365D;">{tech_name}</div>
            <div style="font-size: 12px; color: #64748B; margin-top: 4px;">Aspect Model: <strong>{aspect_model}</strong> | Blocks: <strong>{len(sig.blocks)}</strong></div>
        </div>
        """

        signals_data = []
        for s in sig.signals:
            sig_pos = s.offset_m
            lock_time = s.sighting_distance_m
            sig_type = s.signal_type.value if hasattr(s.signal_type, "value") else str(s.signal_type)
            signals_data.append([
                s.signal_id,
                s.link_id,
                f"{sig_pos:.1f}",
                sig_type,
                aspect_model,
                f"{lock_time:.1f} s",
            ])

        return gr.update(choices=tt_names, value=cur_tt.train_type_id), spec_card, fig_tr, fig_dv, sig_card, signals_data

    components["btn_refresh_rs"].click(
        fn=update_rs_view,
        inputs=[components["train_selector"]],
        outputs=[
            components["train_selector"],
            components["rs_spec_card"],
            components["plot_traction"],
            components["plot_davis"],
            components["signalling_info_card"],
            components["tbl_signals"],
        ],
    )

    components["train_selector"].change(
        fn=update_rs_view,
        inputs=[components["train_selector"]],
        outputs=[
            components["train_selector"],
            components["rs_spec_card"],
            components["plot_traction"],
            components["plot_davis"],
            components["signalling_info_card"],
            components["tbl_signals"],
        ],
    )

    return components


create_rolling_stock_tab = create_rolling_stock_signalling_tab

