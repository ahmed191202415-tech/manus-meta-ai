
from typing import Dict, Any
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.config import EXPORT_DIR
from app.schemas.report_requests import SaveDocxReportRequest
from app.utils.files import sanitize_file_name


def save_docx_report_local(body: SaveDocxReportRequest) -> Dict[str, Any]:
    file_name = sanitize_file_name(body.file_name, "report", "docx")
    output_path = EXPORT_DIR / file_name

    doc = Document()

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = title.add_run(body.title)
    run.bold = True
    run.font.size = Pt(18)

    if body.subtitle:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.add_run(body.subtitle)

    for section in body.sections:
        if section.heading:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            r = p.add_run(section.heading)
            r.bold = True
            r.font.size = Pt(14)

        for paragraph in section.paragraphs:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p.add_run(paragraph)

        if section.table_headers:
            table = doc.add_table(rows=1, cols=len(section.table_headers))
            table.style = "Table Grid"

            hdr_cells = table.rows[0].cells
            for i, header in enumerate(section.table_headers):
                hdr_cells[i].text = str(header)

            for row in section.table_rows:
                cells = table.add_row().cells
                for i, value in enumerate(row):
                    cells[i].text = str(value)

    doc.save(output_path)

    return {
        "success": True,
        "file_name": file_name,
        "file_path": str(output_path),
        "export_dir": str(EXPORT_DIR),
    }
