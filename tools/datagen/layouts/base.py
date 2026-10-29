"""Base utilities and NumberedCanvas for deterministic PDF generation."""

from typing import Any
import reportlab.rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate

# Ensure byte-identical invariant PDF outputs
reportlab.rl_config.invariant = 1


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas that writes 'Page X of Y' and consistent footer metadata."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_footer(num_pages)
            super().showPage()
        super().save()

    def draw_footer(self, total_pages: int) -> None:
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Thin footer rule
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(36, 32, letter[0] - 36, 32)

        # Page numbering on right
        page_str = f"Page {self._pageNumber} of {total_pages}"
        self.drawRightString(letter[0] - 36, 20, page_str)

        # Subtle notice on left
        self.drawString(36, 20, "Generated Invoice • Valid Electronic Document")
        self.restoreState()


def get_base_styles() -> dict[str, ParagraphStyle]:
    """Return base paragraph styles for layouts."""
    base_sheet = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}

    styles["Normal"] = ParagraphStyle(
        "BaseNormal",
        parent=base_sheet["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#1e293b"),
    )

    styles["Small"] = ParagraphStyle(
        "BaseSmall",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#64748b"),
    )

    styles["Bold"] = ParagraphStyle(
        "BaseBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
    )

    styles["Title"] = ParagraphStyle(
        "BaseTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
    )

    return styles
