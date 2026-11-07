"""v1.14.5: shared HTML snippets for report download buttons.

Every CSV download button in the HTML report uses ``CSV_BUTTON_STYLE``, and related buttons sit
side by side in one ``csv_button_panel``.
"""
from __future__ import annotations

import base64
import html
from typing import Sequence

CSV_BUTTON_STYLE = (
    "display: inline-block; padding: 6px 14px; background-color: #1E3A8A; color: #FFFFFF; "
    "text-decoration: none; border-radius: 4px; font-weight: 600; font-size: 13px;"
)
CSV_PANEL_STYLE = "margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center;"


def csv_download_button(csv_text: str, filename: str, label: str) -> str:
    """Styled ``<a download>`` button carrying ``csv_text`` as a base64 data URI."""
    b64 = base64.b64encode(csv_text.encode("utf-8")).decode("ascii")
    return (
        f'<a href="data:text/csv;base64,{b64}" download="{html.escape(filename, quote=True)}" '
        f'class="csv-download-btn" style="{CSV_BUTTON_STYLE}">📥 {html.escape(label)}</a>'
    )


def csv_button_panel(buttons: Sequence[str]) -> str:
    """Adjacent buttons in one flex row."""
    return f'<div class="csv-download-panel" style="{CSV_PANEL_STYLE}">{"".join(buttons)}</div>'
