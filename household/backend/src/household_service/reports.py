"""PDF point-report generation (reportlab, pure Python — no system
dependencies to add to the container). Reports are written to disk once
and kept, so past reports stay downloadable without regenerating.

Visual language intentionally mirrors the frontend's black-and-white
design (css/tokens.css): black/near-black for primary text and the header
rule, grays for secondary text and zebra striping, and the one semantic
accent (success green) used sparingly for the top performer — the same
restraint the frontend uses accent color for warnings/notifications only.
"""

from datetime import UTC, date, datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import Flowable

REPORTS_DIR = Path("/app/data/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

INK = colors.HexColor("#111111")
MUTED = colors.HexColor("#666666")
BORDER = colors.HexColor("#e2e2e2")
SURFACE = colors.HexColor("#f7f7f7")
ACCENT_SUCCESS = colors.HexColor("#15803d")
ACCENT_SUCCESS_BG = colors.HexColor("#e7f6ec")

PAGE_MARGIN = 20 * mm


class _ShareBar(Flowable):
    """A small horizontal bar showing one row's points as a fraction of
    the period's top scorer — gives the table an at-a-glance shape instead
    of just a column of numbers."""

    def __init__(self, fraction: float, width: float = 32 * mm, height: float = 3 * mm):
        super().__init__()
        self.fraction = max(0.0, min(1.0, fraction))
        self.width = width
        self.height = height

    def wrap(self, *_args):
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        canvas.setFillColor(BORDER)
        canvas.roundRect(
            0, 0, self.width, self.height, self.height / 2, stroke=0, fill=1
        )
        if self.fraction > 0:
            canvas.setFillColor(INK)
            fill_width = max(self.height, self.width * self.fraction)
            canvas.roundRect(
                0, 0, fill_width, self.height, self.height / 2, stroke=0, fill=1
            )


def _styles():
    base = getSampleStyleSheet()
    return {
        "eyebrow": ParagraphStyle(
            "eyebrow",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            textColor=MUTED,
            spaceAfter=2,
            leading=10,
        ),
        "title": ParagraphStyle(
            "reportTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=INK,
            alignment=0,
            spaceAfter=0,
            leading=26,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["Normal"],
            fontSize=11,
            textColor=MUTED,
            spaceAfter=0,
        ),
        "meta_right": ParagraphStyle(
            "metaRight",
            parent=base["Normal"],
            fontSize=8.5,
            textColor=MUTED,
            alignment=TA_RIGHT,
            leading=12,
        ),
        "stat_value": ParagraphStyle(
            "statValue",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=20,
            textColor=INK,
            leading=22,
        ),
        "stat_label": ParagraphStyle(
            "statLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            textColor=MUTED,
            spaceBefore=1,
            leading=9,
        ),
        "empty": ParagraphStyle(
            "empty", parent=base["Normal"], textColor=MUTED, fontSize=10
        ),
    }


def _header_block(
    styles,
    period_type: str,
    period_start: date,
    period_end: date,
    generated_by: str,
    generated_at: datetime,
):
    period_label = (
        f"{period_start.strftime('%d %b %Y')} – {period_end.strftime('%d %b %Y')}"
    )
    header_table = Table(
        [
            [
                Paragraph("HOUSEHOLD SYSTEM", styles["eyebrow"]),
                Paragraph(
                    f"Generated {generated_at.strftime('%d %b %Y, %H:%M')}<br/>by {generated_by}",
                    styles["meta_right"],
                ),
            ]
        ],
        colWidths=[None, 60 * mm],
    )
    header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    return [
        header_table,
        Paragraph(f"{period_type.capitalize()} points report", styles["title"]),
        Paragraph(period_label, styles["subtitle"]),
        Spacer(1, 4 * mm),
        HRFlowable(width="100%", thickness=1.4, color=INK, spaceAfter=8 * mm),
    ]


def _stat_cell(value: str, label: str, styles) -> list:
    return [
        Paragraph(value, styles["stat_value"]),
        Paragraph(label.upper(), styles["stat_label"]),
    ]


def _summary_row(rows: list[tuple[str, int]], eur_rate: float | None, styles):
    total_points = sum(points for _, points in rows)
    participants = len(rows)
    top_name = rows[0][0] if rows else "—"

    cells = [
        _stat_cell(str(total_points), "Total points", styles),
        _stat_cell(str(participants), "Participants", styles),
        _stat_cell(top_name, "Top performer", styles),
    ]
    if eur_rate:
        cells.append(
            _stat_cell(f"{total_points * eur_rate:.2f} €", "Total value", styles)
        )

    table = Table([cells], colWidths=[None] * len(cells))
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0, colors.white),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.75, BORDER),
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
            ]
        )
    )
    return table


def _leaderboard_table(rows: list[tuple[str, int]], eur_rate: float | None, styles):
    max_points = max((points for _, points in rows), default=0)

    header = ["#", "User", "Points"]
    if eur_rate:
        header.append("≈ EUR")
    header.append("Share")

    data = [header]
    for i, (name, points) in enumerate(rows, start=1):
        row = [str(i), name, str(points)]
        if eur_rate:
            row.append(f"{points * eur_rate:.2f} €")
        row.append(_ShareBar(points / max_points if max_points else 0))
        data.append(row)

    col_widths = [10 * mm, None, 22 * mm]
    if eur_rate:
        col_widths.append(24 * mm)
    col_widths.append(38 * mm)

    table = Table(data, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("LINEBELOW", (0, 0), (-1, 0), 0, colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURFACE]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "LEFT"),
    ]
    # The top scorer gets a subtle highlight — same green the frontend
    # reserves for "success" states (badge-success in components.css).
    if rows:
        style.append(("BACKGROUND", (0, 1), (-1, 1), ACCENT_SUCCESS_BG))
        style.append(("TEXTCOLOR", (0, 1), (1, 1), ACCENT_SUCCESS))
        style.append(("FONTNAME", (0, 1), (1, 1), "Helvetica-Bold"))
    table.setStyle(TableStyle(style))
    return table


def _footer(generated_by: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        y = PAGE_MARGIN - 6 * mm
        canvas.line(PAGE_MARGIN, y, A4[0] - PAGE_MARGIN, y)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(
            PAGE_MARGIN, y - 10, f"Household System · generated by {generated_by}"
        )
        canvas.drawRightString(
            A4[0] - PAGE_MARGIN, y - 10, f"Page {canvas.getPageNumber()}"
        )
        canvas.restoreState()

    return draw


def generate_report_pdf(
    *,
    report_id: int,
    period_type: str,
    period_start: date,
    period_end: date,
    rows: list[tuple[str, int]],
    eur_rate: float | None,
    generated_by: str = "an admin",
    generated_at: datetime | None = None,
) -> str:
    """Writes the PDF to REPORTS_DIR and returns its filename."""
    filename = f"report-{report_id}-{period_start.isoformat()}.pdf"
    path = REPORTS_DIR / filename
    generated_at = generated_at or datetime.now(UTC)

    styles = _styles()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        title="Household points report",
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
    )

    story = _header_block(
        styles, period_type, period_start, period_end, generated_by, generated_at
    )

    if not rows:
        story.append(
            Paragraph("No points were logged in this period.", styles["empty"])
        )
    else:
        story.append(_summary_row(rows, eur_rate, styles))
        story.append(Spacer(1, 8 * mm))
        story.append(_leaderboard_table(rows, eur_rate, styles))

    footer = _footer(generated_by)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return filename
