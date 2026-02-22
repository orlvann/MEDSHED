"""Build XLSX files for schedule exports (personal & team)."""

from __future__ import annotations

import calendar
from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from backend.utils.exporters import DoctorExportData, TeamExportData

_MONTH_NAMES_PL = {
    1: "STYCZE\u0143",
    2: "LUTY",
    3: "MARZEC",
    4: "KWIECIE\u0143",
    5: "MAJ",
    6: "CZERWIEC",
    7: "LIPIEC",
    8: "SIERPIE\u0143",
    9: "WRZESIE\u0143",
    10: "PA\u0179DZIERNIK",
    11: "LISTOPAD",
    12: "GRUDZIE\u0143",
}

_DAY_NAMES_PL_FULL = {
    0: "poniedzia\u0142ek",
    1: "wtorek",
    2: "\u015broda",
    3: "czwartek",
    4: "pi\u0105tek",
    5: "sobota",
    6: "niedziela",
}

_WEEKEND_DAYS = {5, 6}  # Saturday, Sunday


def build_xlsx(data: DoctorExportData) -> bytes:
    """Personal schedule: MONTH_YEAR, LastName, day+weekday + DYŻUR/PODDYŻUR."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None

    month_pl = _MONTH_NAMES_PL.get(data.month, str(data.month))
    ws.title = f"{month_pl}_{data.year}"

    # ---- styles -----------------------------------------------------------
    title_font = Font(bold=True, size=14)
    subtitle_font = Font(bold=True, size=11)
    header_font = Font(bold=True, size=10, color="FFFFFF")
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    weekend_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="B4B4B4"),
        right=Side(style="thin", color="B4B4B4"),
        top=Side(style="thin", color="B4B4B4"),
        bottom=Side(style="thin", color="B4B4B4"),
    )
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    # ---- title row --------------------------------------------------------
    ws.merge_cells("A1:B1")
    cell = ws["A1"]
    cell.value = f"{month_pl}_{data.year}"
    cell.font = title_font
    cell.alignment = left
    ws.row_dimensions[1].height = 28

    # ---- subtitle (doctor name) -------------------------------------------
    ws.merge_cells("A2:B2")
    cell2 = ws["A2"]
    cell2.value = data.last_name
    cell2.font = subtitle_font
    cell2.alignment = left
    ws.row_dimensions[2].height = 22

    # ---- column headers ---------------------------------------------------
    row = 4
    headers = ["", "DY\u017bUR / PODDY\u017bUR"]
    for col_idx, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=col_idx, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = center
        c.border = thin_border

    # ---- data rows (only days with assignments) ---------------------------
    shift_by_day: dict[int, list[str]] = {}
    for asn in data.assignments:
        day = asn["day"]
        shift_type = asn["shift_type"]
        shift_by_day.setdefault(day, []).append(shift_type)

    row = 5
    body_font = Font(size=10)
    for day in sorted(shift_by_day.keys()):
        d = date(data.year, data.month, day)
        weekday = d.weekday()
        day_name = _DAY_NAMES_PL_FULL.get(weekday, "")
        is_weekend = weekday in _WEEKEND_DAYS

        shifts = shift_by_day[day]
        labels = []
        for s in sorted(shifts):
            labels.append("DY\u017bUR" if s == "onsite" else "PODDY\u017bUR")
        shift_label = ", ".join(labels)

        ws.cell(row=row, column=1, value=f"{day} {day_name}").alignment = left
        ws.cell(row=row, column=1).font = body_font
        ws.cell(row=row, column=2, value=shift_label).alignment = center
        ws.cell(row=row, column=2).font = body_font

        for col_idx in range(1, 3):
            c = ws.cell(row=row, column=col_idx)
            c.border = thin_border
            if is_weekend:
                c.fill = weekend_fill

        row += 1

    # ---- auto column widths -----------------------------------------------
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 24

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_team_xlsx(data: TeamExportData) -> bytes:
    """Team schedule: MONTH_YEAR title, columns: day+weekday, DYŻUR, PODDYŻUR.

    When shift_type_filter is set, only the matching column is included.
    """
    wb = Workbook()
    ws = wb.active
    assert ws is not None

    month_pl = _MONTH_NAMES_PL.get(data.month, str(data.month))
    num_days = calendar.monthrange(data.year, data.month)[1]

    # ---- determine which columns to show ----------------------------------
    show_onsite = data.shift_type_filter in (None, "onsite")
    show_oncall = data.shift_type_filter in (None, "oncall")

    # ---- styles -----------------------------------------------------------
    title_font = Font(bold=True, size=14)
    header_font = Font(bold=True, size=10, color="FFFFFF")
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    weekend_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="B4B4B4"),
        right=Side(style="thin", color="B4B4B4"),
        top=Side(style="thin", color="B4B4B4"),
        bottom=Side(style="thin", color="B4B4B4"),
    )
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    # ---- header columns ---------------------------------------------------
    headers: list[str] = [""]
    if show_onsite:
        headers.append("DY\u017bUR")
    if show_oncall:
        headers.append("PODDY\u017bUR")
    num_cols = len(headers)

    # ---- title row --------------------------------------------------------
    last_col_letter = chr(ord("A") + num_cols - 1)
    ws.merge_cells(f"A1:{last_col_letter}1")
    cell = ws["A1"]
    cell.value = f"{month_pl}_{data.year}"
    cell.font = title_font
    cell.alignment = left
    ws.row_dimensions[1].height = 30
    ws.title = f"{month_pl}_{data.year}"

    # ---- column headers ---------------------------------------------------
    row = 3
    for col_idx, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=col_idx, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = center
        c.border = thin_border

    # ---- build lookup: day -> {onsite: [names], oncall: [names]} ----------
    day_map: dict[int, dict[str, list[str]]] = {}
    for day_num in range(1, num_days + 1):
        day_map[day_num] = {"onsite": [], "oncall": []}

    for asn in data.assignments:
        day = asn["day"]
        shift = asn["shift_type"]
        name = asn.get("doctor_last_name", asn.get("doctor_name", ""))
        if day in day_map and shift in day_map[day]:
            day_map[day][shift].append(name)

    # ---- data rows --------------------------------------------------------
    row = 4
    body_font = Font(size=10)
    for day_num in range(1, num_days + 1):
        d = date(data.year, data.month, day_num)
        weekday = d.weekday()
        day_name = _DAY_NAMES_PL_FULL.get(weekday, "")
        is_weekend = weekday in _WEEKEND_DAYS

        col = 1
        ws.cell(row=row, column=col, value=f"{day_num} {day_name}").alignment = left
        ws.cell(row=row, column=col).font = body_font
        col += 1

        if show_onsite:
            ws.cell(row=row, column=col, value=", ".join(day_map[day_num]["onsite"])).alignment = center
            ws.cell(row=row, column=col).font = body_font
            col += 1

        if show_oncall:
            ws.cell(row=row, column=col, value=", ".join(day_map[day_num]["oncall"])).alignment = center
            ws.cell(row=row, column=col).font = body_font
            col += 1

        for ci in range(1, num_cols + 1):
            c = ws.cell(row=row, column=ci)
            c.border = thin_border
            if is_weekend:
                c.fill = weekend_fill

        row += 1

    # ---- column widths ----------------------------------------------------
    ws.column_dimensions["A"].width = 22
    if num_cols >= 2:
        ws.column_dimensions["B"].width = 22
    if num_cols >= 3:
        ws.column_dimensions["C"].width = 22

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
