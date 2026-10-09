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

from household_service.i18n import Lang, t

REPORTS_DIR = Path("/app/data/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

INK = colors.HexColor("#111111")
MUTED = colors.HexColor("#666666")
BORDER = colors.HexColor("#e2e2e2")
SURFACE = colors.HexColor("#f7f7f7")
ACCENT_SUCCESS = colors.HexColor("#15803d")
ACCENT_SUCCESS_BG = colors.HexColor("#e7f6ec")

PAGE_MARGIN = 20 * mm


def _fmt_date(d: date, lang: Lang) -> str:
    # English keeps the "06 Oct 2026" month-abbreviation form; German
    # uses the idiomatic numeric "06.10.2026" instead of transliterating
    # month names, which would need a separate lookup table for no
    # real benefit here.
    return d.strftime("%d.%m.%Y") if lang == "de" else d.strftime("%d %b %Y")


def _fmt_datetime(dt: datetime, lang: Lang) -> str:
    return (
        dt.strftime("%d.%m.%Y, %H:%M")
        if lang == "de"
        else dt.strftime("%d %b %Y, %H:%M")
    )


def _fmt_amount(value: float, lang: Lang) -> str:
    # German number formatting uses a decimal comma, not a point.
    text = f"{value:.2f}"
    return text.replace(".", ",") if lang == "de" else text


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
            fontSize=16,
            textColor=INK,
            leading=18,
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
    lang: Lang,
):
    period_label = f"{_fmt_date(period_start, lang)} – {_fmt_date(period_end, lang)}"
    header_table = Table(
        [
            [
                Paragraph("HOUSEHOLD SYSTEM", styles["eyebrow"]),
                Paragraph(
                    t(
                        lang,
                        "report_pdf.generated_by",
                        date=_fmt_datetime(generated_at, lang),
                        by=generated_by,
                    ),
                    styles["meta_right"],
                ),
            ]
        ],
        colWidths=[None, 60 * mm],
    )
    header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    title = t(lang, f"report_pdf.title.{period_type}")
    return [
        header_table,
        Paragraph(title, styles["title"]),
        Paragraph(period_label, styles["subtitle"]),
        Spacer(1, 4 * mm),
        HRFlowable(width="100%", thickness=1.4, color=INK, spaceAfter=8 * mm),
    ]


def _stat_cell(value: str, label: str, styles) -> list:
    return [
        Paragraph(value, styles["stat_value"]),
        Paragraph(label.upper(), styles["stat_label"]),
    ]


def _summary_row(
    rows: list[tuple[str, int]], rate: float | None, currency: str, styles, lang: Lang
):
    total_points = sum(points for _, points in rows)
    participants = len(rows)
    top_name = rows[0][0] if rows else "—"

    cells = [
        _stat_cell(str(total_points), t(lang, "report_pdf.stat.total_points"), styles),
        _stat_cell(str(participants), t(lang, "report_pdf.stat.participants"), styles),
        _stat_cell(top_name, t(lang, "report_pdf.stat.top_performer"), styles),
    ]
    if rate:
        cells.append(
            _stat_cell(
                f"{_fmt_amount(rate, lang)} {currency}",
                t(lang, "report_pdf.stat.money_per_point"),
                styles,
            )
        )
        cells.append(
            _stat_cell(
                f"{_fmt_amount(total_points * rate, lang)} {currency}",
                t(lang, "report_pdf.stat.total_value"),
                styles,
            )
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


def _leaderboard_table(
    rows: list[tuple[str, int]], rate: float | None, currency: str, styles, lang: Lang
):
    max_points = max((points for _, points in rows), default=0)

    header = [
        t(lang, "report_pdf.table.rank"),
        t(lang, "report_pdf.table.user"),
        t(lang, "report_pdf.table.points"),
    ]
    if rate:
        header.append(t(lang, "report_pdf.table.approx_currency", currency=currency))
    header.append(t(lang, "report_pdf.table.share"))

    data = [header]
    for i, (name, points) in enumerate(rows, start=1):
        row = [str(i), name, str(points)]
        if rate:
            row.append(f"{_fmt_amount(points * rate, lang)} {currency}")
        row.append(_ShareBar(points / max_points if max_points else 0))
        data.append(row)

    col_widths = [10 * mm, None, 22 * mm]
    if rate:
        col_widths.append(26 * mm)
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


def _footer(generated_by: str, lang: Lang):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        y = PAGE_MARGIN - 6 * mm
        canvas.line(PAGE_MARGIN, y, A4[0] - PAGE_MARGIN, y)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(
            PAGE_MARGIN,
            y - 10,
            t(lang, "report_pdf.footer", by=generated_by),
        )
        canvas.drawRightString(
            A4[0] - PAGE_MARGIN,
            y - 10,
            t(lang, "report_pdf.page_number", n=canvas.getPageNumber()),
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
    rate: float | None,
    currency: str = "EUR",
    generated_by: str | None = None,
    generated_at: datetime | None = None,
    lang: Lang = "en",
) -> str:
    """Writes the PDF to REPORTS_DIR and returns its filename.

    `lang` is the household's shared HouseholdSettings.default_language
    (see household_service.i18n's module docstring) — a report is one
    document, not per-viewer, so it can't follow each admin's own
    preference the way a notification follows its one recipient."""
    filename = f"report-{report_id}-{period_start.isoformat()}.pdf"
    path = REPORTS_DIR / filename
    generated_at = generated_at or datetime.now(UTC)
    generated_by_label = generated_by or t(lang, "report_pdf.automatic")

    styles = _styles()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        title=t(lang, f"report_pdf.title.{period_type}"),
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
    )

    story = _header_block(
        styles,
        period_type,
        period_start,
        period_end,
        generated_by_label,
        generated_at,
        lang,
    )

    if not rows:
        story.append(Paragraph(t(lang, "report_pdf.empty"), styles["empty"]))
    else:
        story.append(_summary_row(rows, rate, currency, styles, lang))
        story.append(Spacer(1, 8 * mm))
        story.append(_leaderboard_table(rows, rate, currency, styles, lang))

    footer = _footer(generated_by_label, lang)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return filename
