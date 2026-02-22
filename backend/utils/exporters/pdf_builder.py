"""Build PDF files for schedule exports (personal & team)."""

from __future__ import annotations

import calendar
import os
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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

_HEADER_BG = colors.HexColor("#2F5496")
_WEEKEND_BG = colors.HexColor("#FFF2CC")

# Candidate paths for a Unicode-capable TTF font (supports Polish diacritics).
_FONT_CANDIDATES = [
    # reportlab bundled
    "{rl}/fonts/DejaVuSans.ttf",
    # Debian/Ubuntu system fonts
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    # Alpine Linux
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    # macOS
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    # Windows
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/calibri.ttf",
]


def _register_font() -> str:
    """Register a Unicode-capable font; return its name.

    Searches multiple system paths so Polish diacritics render correctly.
    """
    import reportlab as _rl

    rl_dir = os.path.dirname(_rl.__file__)

    for tpl in _FONT_CANDIDATES:
        path = tpl.replace("{rl}", rl_dir)
        if os.path.isfile(path):
            try:
                font_name = os.path.splitext(os.path.basename(path))[0]
                pdfmetrics.registerFont(TTFont(font_name, path))
                return font_name
            except Exception:
                continue

    return "Helvetica"


def build_pdf(data: DoctorExportData) -> bytes:
    """Personal schedule PDF: MONTH_YEAR, LastName, day+weekday + shift type."""
    font_name = _register_font()

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=15 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ExportTitle",
        parent=styles["Heading1"],
        fontName=font_name,
        fontSize=16,
        leading=20,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ExportSubtitle",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=12,
        leading=16,
        spaceAfter=6,
    )

    story: list = []

    # ---- title ------------------------------------------------------------
    month_pl = _MONTH_NAMES_PL.get(data.month, str(data.month))
    story.append(Paragraph(f"{month_pl}_{data.year}", title_style))
    story.append(Paragraph(data.last_name, subtitle_style))
    story.append(Spacer(1, 6 * mm))

    # ---- table ------------------------------------------------------------
    table_data = [["", "DY\u017bUR / PODDY\u017bUR"]]

    # Build lookup: day -> list of shift types
    shift_by_day: dict[int, list[str]] = {}
    for asn in sorted(data.assignments, key=lambda a: (a["day"], a["shift_type"])):
        shift_by_day.setdefault(asn["day"], []).append(asn["shift_type"])

    weekend_rows: list[int] = []

    for day in sorted(shift_by_day.keys()):
        d = date(data.year, data.month, day)
        weekday = d.weekday()
        day_name = _DAY_NAMES_PL_FULL.get(weekday, "")

        labels = []
        for s in sorted(shift_by_day[day]):
            labels.append("DY\u017bUR" if s == "onsite" else "PODDY\u017bUR")
        shift_label = ", ".join(labels)

        table_data.append([f"{day} {day_name}", shift_label])
        if weekday in _WEEKEND_DAYS:
            weekend_rows.append(len(table_data) - 1)

    col_widths = [55 * mm, 60 * mm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        # header
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), font_name),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        # body
        ("FONTNAME", (0, 1), (-1, -1), font_name),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        # alignment
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # grid
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B4B4B4")),
        # padding
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]

    for wr in weekend_rows:
        style_cmds.append(("BACKGROUND", (0, wr), (-1, wr), _WEEKEND_BG))

    table.setStyle(TableStyle(style_cmds))
    story.append(table)

    doc.build(story)
    return buf.getvalue()


def build_team_pdf(data: TeamExportData) -> bytes:
    """Team schedule PDF: MONTH_YEAR, day+weekday / DYŻUR / PODDYŻUR columns.

    When shift_type_filter is set, only the matching column is included.
    """
    font_name = _register_font()

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=15 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TeamExportTitle",
        parent=styles["Heading1"],
        fontName=font_name,
        fontSize=16,
        leading=20,
        spaceAfter=6,
    )

    story: list = []

    # ---- title ------------------------------------------------------------
    month_pl = _MONTH_NAMES_PL.get(data.month, str(data.month))
    story.append(Paragraph(f"{month_pl}_{data.year}", title_style))
    story.append(Spacer(1, 4 * mm))

    # ---- build lookup: day -> {onsite: [names], oncall: [names]} ----------
    num_days = calendar.monthrange(data.year, data.month)[1]
    day_map: dict[int, dict[str, list[str]]] = {}
    for day_num in range(1, num_days + 1):
        day_map[day_num] = {"onsite": [], "oncall": []}

    for asn in data.assignments:
        day = asn["day"]
        shift = asn["shift_type"]
        name = asn.get("doctor_last_name", asn.get("doctor_name", ""))
        if day in day_map and shift in day_map[day]:
            day_map[day][shift].append(name)

    # ---- determine which columns to show ----------------------------------
    show_onsite = data.shift_type_filter in (None, "onsite")
    show_oncall = data.shift_type_filter in (None, "oncall")

    # ---- table header -----------------------------------------------------
    header_row: list[str] = [""]
    if show_onsite:
        header_row.append("DY\u017bUR")
    if show_oncall:
        header_row.append("PODDY\u017bUR")

    table_data: list[list[str]] = [header_row]
    weekend_rows: list[int] = []

    for day_num in range(1, num_days + 1):
        d = date(data.year, data.month, day_num)
        weekday = d.weekday()
        day_name = _DAY_NAMES_PL_FULL.get(weekday, "")

        row: list[str] = [f"{day_num} {day_name}"]
        if show_onsite:
            row.append(", ".join(day_map[day_num]["onsite"]))
        if show_oncall:
            row.append(", ".join(day_map[day_num]["oncall"]))

        table_data.append(row)
        if weekday in _WEEKEND_DAYS:
            weekend_rows.append(len(table_data) - 1)

    # ---- column widths ----------------------------------------------------
    num_cols = len(header_row)
    if num_cols == 3:
        col_widths = [50 * mm, 55 * mm, 55 * mm]
    else:
        col_widths = [55 * mm, 65 * mm]

    table = Table(table_data, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        # header
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), font_name),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        # body
        ("FONTNAME", (0, 1), (-1, -1), font_name),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        # alignment
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # grid
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B4B4B4")),
        # padding
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]

    for wr in weekend_rows:
        style_cmds.append(("BACKGROUND", (0, wr), (-1, wr), _WEEKEND_BG))

    table.setStyle(TableStyle(style_cmds))
    story.append(table)

    doc.build(story)
    return buf.getvalue()
