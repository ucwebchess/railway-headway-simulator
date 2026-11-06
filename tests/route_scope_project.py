"""v1.12.0 — synthetic 100-TrackLink project whose service route is a 10-link mid section.

Built in a temp dir from the shipped 06_multilink_blocks workbooks (never modified): the
topology, signalling and operations sheets are rewritten so that

  * the network is LNK_001..LNK_100 on one BIDIRECTIONAL track (ND_000 -> ND_100),
  * every link is exactly one block, with signals at the link ends,
  * ROUTE_LINK_SEQUENCE = LNK_046..LNK_055 (10 links), no station stops, no tunnels,
  * on-route links alternate 120 / 80 km/h (one envelope step per link) and off-route
    links are 60 km/h, so any off-route leak shows up in the speed range.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import openpyxl

N_LINKS = 100
ROUTE_FIRST, ROUTE_LAST = 46, 55
ROUTE = [f"LNK_{k:03d}" for k in range(ROUTE_FIRST, ROUTE_LAST + 1)]
EXAMPLE_06 = Path(__file__).resolve().parents[1] / "examples" / "06_multilink_blocks"


def link_len(k: int) -> float:
    return 400.0 + 10.0 * k  # 410 .. 1400 m, all distinct


def link_speed(k: int) -> float:
    if ROUTE_FIRST <= k <= ROUTE_LAST:
        return 80.0 if k % 2 else 120.0
    return 60.0


ROUTE_LENGTH_M = sum(link_len(k) for k in range(ROUTE_FIRST, ROUTE_LAST + 1))  # 9050 m
NETWORK_LENGTH_M = sum(link_len(k) for k in range(1, N_LINKS + 1))  # 90500 m


def _rewrite(ws, rows: list[dict]) -> None:
    hdr = [c.value for c in ws[1]]
    if ws.max_row >= 3:
        ws.delete_rows(3, ws.max_row - 2)
    for i, row in enumerate(rows):
        unknown = set(row) - set(hdr)
        assert not unknown, (ws.title, unknown)
        for j, h in enumerate(hdr, start=1):
            if h in row:
                ws.cell(3 + i, j, row[h])


def build_route_scope_project(dst: Path, route: list[str] | None = None) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    for f in EXAMPLE_06.glob("*.xlsx"):
        shutil.copy(f, dst / f.name)

    nodes = [
        {"NODE_ID": f"ND_{k:03d}", "DESCRIPTION": "", "NODE_TYPE": "ENDPOINT" if k in (0, N_LINKS) else "JUNCTION"}
        for k in range(N_LINKS + 1)
    ]
    links = [
        {
            "LINK_ID": f"LNK_{k:03d}", "TRACK_ID": "TRK_M1",
            "START_NODE_ID": f"ND_{k - 1:03d}", "END_NODE_ID": f"ND_{k:03d}",
            "LENGTH_M": link_len(k), "MAX_SPEED_KMH": link_speed(k),
            "GRADIENT_PERMIL": 0.0, "CURVATURE_RADIUS_M": 0.0,
        }
        for k in range(1, N_LINKS + 1)
    ]
    wb = openpyxl.load_workbook(dst / "01_Infrastructure.xlsx")
    _rewrite(wb["Nodes"], nodes)
    _rewrite(wb["TrackLinks"], links)
    for s in ("Stations", "PlatformSpans", "Tunnels", "TVSSections", "TVSGeometry"):  # v1.14.0 schema
        _rewrite(wb[s], [])
    wb.save(dst / "01_Infrastructure.xlsx")

    sig = {"DIRECTION": "NOMINAL", "SIGNAL_TYPE": "MAIN", "SIGHTING_DISTANCE_M": 200.0}
    signals = [{"SIGNAL_ID": f"SIG_{k:03d}", "LINK_ID": f"LNK_{k:03d}", "OFFSET_M": 0.0, **sig} for k in range(1, N_LINKS + 1)]
    signals.append({"SIGNAL_ID": f"SIG_{N_LINKS + 1:03d}", "LINK_ID": f"LNK_{N_LINKS:03d}", "OFFSET_M": link_len(N_LINKS), **sig})
    blocks = [
        {"BLOCK_ID": f"BLK_{k:03d}", "ENTRY_SIGNAL_ID": f"SIG_{k:03d}", "EXIT_SIGNAL_ID": f"SIG_{k + 1:03d}",
         "OVERLAP_M": 50.0, "RELEASE_DELAY_S": 4.0}
        for k in range(1, N_LINKS + 1)
    ]
    geometry = [
        {"BLOCK_ID": f"BLK_{k:03d}", "SEQUENCE": 1, "LINK_ID": f"LNK_{k:03d}", "START_OFFSET_M": 0.0, "END_OFFSET_M": link_len(k)}
        for k in range(1, N_LINKS + 1)
    ]
    wb = openpyxl.load_workbook(dst / "02_Signalling.xlsx")
    _rewrite(wb["Signals"], signals)
    _rewrite(wb["Blocks"], blocks)
    _rewrite(wb["BlockGeometry"], geometry)
    _rewrite(wb["InterlockingRoutes"], [])
    wb.save(dst / "02_Signalling.xlsx")

    wb = openpyxl.load_workbook(dst / "04_Operations.xlsx")
    sp = wb["ServicePatterns"]
    hdr = [c.value for c in sp[1]]
    sp.cell(3, hdr.index("ROUTE_LINK_SEQUENCE") + 1, ",".join(route or ROUTE))
    _rewrite(wb["StoppingPatterns"], [])
    wb.save(dst / "04_Operations.xlsx")
    return dst


def load_route_scope_project(dst: Path, route: list[str] | None = None):
    from headway.ui.file_manager import FileManager

    d = build_route_scope_project(dst, route)
    project, _report, _fm = FileManager.import_excel_files([str(p) for p in sorted(d.glob("*.xlsx"))])
    assert project is not None
    return project
