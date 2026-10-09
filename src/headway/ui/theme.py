"""Professional engineering theme and styling for the Railway Headway Simulator UI.

Implements styling aligned with the reference engineering report specifications:
- Dark navy headings
- Blue primary accents
- Teal secondary accents
- Clean neutral backgrounds
- Distinct status indicators (Success, Warning, Critical)
"""

import gradio as gr

# Custom CSS for polished engineering styling
ENGINEERING_CUSTOM_CSS = """
/* Engineering Theme Overrides */
:root {
    --navy-header: #0f2b48;
    --navy-text: #1a365d;
    --accent-blue: #1e5c99;
    --accent-teal: #00828a;
    --status-green: #2e7d32;
    --status-amber: #e65100;
    --status-red: #c62828;
    --neutral-light: #f8fafc;
    --border-color: #cbd5e1;
}

.gradio-container {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
    max-width: 1400px !important;
    margin: 0 auto !important;
}

.headway-header {
    background: linear-gradient(135deg, #0a1f33 0%, #173f67 100%);
    color: #ffffff !important;
    padding: 24px 28px;
    border-radius: 8px;
    margin-bottom: 20px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}

.headway-header h1 {
    color: #ffffff !important;
    font-size: 26px !important;
    font-weight: 700 !important;
    margin: 0 0 6px 0 !important;
    letter-spacing: -0.02em;
}

.headway-header p {
    color: #cbd5e1 !important;
    font-size: 14px !important;
    margin: 0 !important;
}

.badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    margin-right: 8px;
}

.badge-version {
    background-color: #1e5c99;
    color: #ffffff;
}

.badge-phase {
    background-color: #00828a;
    color: #ffffff;
}

.badge-env {
    background-color: #334155;
    color: #f1f5f9;
}

.kpi-card {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 16px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.kpi-title {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    color: #64748b;
    margin-bottom: 6px;
    letter-spacing: 0.05em;
}

.kpi-value-placeholder {
    font-size: 15px;
    font-weight: 500;
    color: #94a3b8;
    font-style: italic;
}

.kpi-unit {
    font-size: 12px;
    color: #94a3b8;
    margin-left: 4px;
}

.placeholder-box {
    background-color: #f8fafc;
    border: 1px dashed #94a3b8;
    border-radius: 8px;
    padding: 32px 24px;
    text-align: center;
    margin: 16px 0;
}

.placeholder-box h3 {
    color: #0f2b48;
    margin-top: 0;
    font-size: 18px;
}

.placeholder-box p {
    color: #475569;
    font-size: 14px;
    max-width: 650px;
    margin: 8px auto;
    line-height: 1.5;
}

.status-badge-ok {
    color: #2e7d32;
    font-weight: 600;
}

.status-badge-warn {
    color: #e65100;
    font-weight: 600;
}

.status-badge-err {
    color: #c62828;
    font-weight: 600;
}
"""


def get_engineering_theme() -> gr.Theme:
    """Construct a clean, professional Gradio theme for railway engineering."""
    theme = gr.themes.Default(
        primary_hue="blue",
        secondary_hue="cyan",
        neutral_hue="slate",
    ).set(
        body_background_fill="#f8fafc",
        block_background_fill="#ffffff",
        block_border_width="1px",
        block_border_color="#e2e8f0",
        block_title_text_color="#0f2b48",
        block_label_text_color="#1e293b",
        button_primary_background_fill="#1e5c99",
        button_primary_background_fill_hover="#174878",
        button_primary_text_color="#ffffff",
    )
    return theme
