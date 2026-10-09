"""Reusable UI components and layout helpers for the Railway Headway Simulator."""

import platform
import sys
from typing import Dict, List, Optional
import gradio as gr

from headway.core.configuration import AppConfig, is_running_in_colab
from headway.core.version import APP_DESCRIPTION, APP_NAME, __version__


def create_header(config: Optional[AppConfig] = None) -> gr.HTML:
    """Render the master application banner with version, phase, and environment badges."""
    ver = config.version if config else __version__
    env = config.environment.value.upper() if config else ("COLAB" if is_running_in_colab() else "DEV")

    html = f"""
    <div class="headway-header">
        <h1>{APP_NAME}</h1>
        <p style="margin-bottom: 10px;">{APP_DESCRIPTION}</p>
        <div>
            <span class="badge badge-version">v{ver}</span>
            <span class="badge badge-phase">Phase: P00 — Foundation</span>
            <span class="badge badge-env">Env: {env}</span>
            <span class="badge" style="background-color: #0f766e; color: #fff;">SRS Parts 1–14 Compliant</span>
        </div>
    </div>
    """
    return gr.HTML(html)


def create_kpi_card(title: str, subtitle: Optional[str] = None) -> gr.HTML:
    """Render a standard engineering KPI card in P00 placeholder state.

    Enforces P00-UI-006: No invented headway, capacity, speed, or bottleneck values.
    """
    sub_html = f'<div style="font-size: 11px; color: #94a3b8;">{subtitle}</div>' if subtitle else ""
    html = f"""
    <div class="kpi-card">
        <div class="kpi-title">{title}</div>
        <div class="kpi-value-placeholder">Not available — simulation engine not implemented</div>
        {sub_html}
    </div>
    """
    return gr.HTML(html)


def create_placeholder_tab(
    tab_name: str,
    milestone_code: str,
    description: str,
    planned_capabilities: Optional[List[str]] = None,
) -> None:
    """Render a standard milestone placeholder inside a navigation tab."""
    cap_list_html = ""
    if planned_capabilities:
        items = "".join(f"<li style='margin-bottom: 4px;'>{cap}</li>" for cap in planned_capabilities)
        cap_list_html = f"""
        <div style="text-align: left; max-width: 650px; margin: 16px auto; background: #ffffff; padding: 14px 20px; border-radius: 6px; border: 1px solid #e2e8f0;">
            <strong style="color: #0f2b48; font-size: 13px;">Planned Capabilities:</strong>
            <ul style="margin: 8px 0 0 18px; padding: 0; color: #334155; font-size: 13px;">
                {items}
            </ul>
        </div>
        """

    box_html = f"""
    <div class="placeholder-box">
        <div style="font-size: 12px; font-weight: 700; color: #00828a; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px;">
            Target Development Milestone: {milestone_code}
        </div>
        <h3 style="margin-bottom: 8px;">{tab_name} Subsystem</h3>
        <p>{description}</p>
        <p style="font-size: 12px; color: #64748b; font-style: italic;">
            Per Governance Directive RHS-MASTER-001 §41, this module is reserved for milestone {milestone_code} and is inactive during P00.
        </p>
        {cap_list_html}
    </div>
    """
    gr.HTML(box_html)


def get_runtime_environment_summary(config: AppConfig) -> Dict[str, str]:
    """Gather diagnostic runtime status information."""
    colab_active = is_running_in_colab()
    return {
        "Python Version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "Platform / OS": f"{platform.system()} {platform.release()}",
        "Google Colab Environment": "Yes (Active)" if colab_active else "No (Standard Host / Sandbox)",
        "App Version": config.version,
        "Environment Mode": config.environment.value,
        "Log Level": config.log_level,
        "Storage Root": str(config.directories.base_dir),
        "Projects Storage": str(config.directories.projects_dir),
        "Reports Storage": str(config.directories.reports_dir),
        "Gradio Server Port": str(config.server.server_port),
        "Public Sharing Enabled": "Yes" if config.server.share else "No (Secure Default)",
    }
