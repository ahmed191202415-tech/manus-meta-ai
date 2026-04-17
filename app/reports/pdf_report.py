from typing import Dict, Any, List
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Table as PdfTable, TableStyle, Paragraph, Spacer

from app.config import EXPORT_DIR
from app.schemas.report_requests import SavePdfReportRequest
from app.utils.files import sanitize_file_name


def save_pdf_report_local(body: SavePdfReportRequest) -> Dict[str, Any]:
    file_name = sanitize_file_name(body.file_name, "report", "pdf")
    output_path = EXPORT_DIR / file_name

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ArabicTitle", parent=styles["Title"], alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="ArabicHeading", parent=styles["Heading2"], alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="ArabicBody", parent=styles["BodyText"], alignment=TA_RIGHT, leading=16))

    story: List[Any] = []
    story.append(Paragraph(body.title, styles["ArabicTitle"]))

    if body.subtitle:
        story.append(Spacer(1, 6))
        story.append(Paragraph(body.subtitle, styles["ArabicBody"]))

    story.append(Spacer(1, 14))

    for section in body.sections:
        if section.heading:
            story.append(Paragraph(section.heading, styles["ArabicHeading"]))
            story.append(Spacer(1, 6))

        for paragraph in section.paragraphs:
            story.append(Paragraph(paragraph, styles["ArabicBody"]))
            story.append(Spacer(1, 6))

        if section.table_headers:
            table_data = [section.table_headers] + section.table_rows
            table = PdfTable(table_data, repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            story.append(table)
            story.append(Spacer(1, 12))

    doc.build(story)

    return {
        "success": True,
        "file_name": file_name,
        "file_path": str(output_path),
        "export_dir": str(EXPORT_DIR),
    }
