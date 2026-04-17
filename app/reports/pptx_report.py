
from typing import Dict, Any
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor

from app.config import EXPORT_DIR
from app.schemas.report_requests import SavePptxReportRequest
from app.utils.files import sanitize_file_name


def rgb(hex_color: str):
    hex_color = hex_color.replace("#", "")
    return RGBColor(int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


PRIMARY = "#1F4E78"
SECONDARY = "#2F75B5"
BG = "#F5F7FB"


def save_pptx_report_local(body: SavePptxReportRequest) -> Dict[str, Any]:
    file_name = sanitize_file_name(body.file_name, "presentation", "pptx")
    output_path = EXPORT_DIR / file_name

    prs = Presentation()

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    title_box = slide.shapes.add_textbox(Inches(0.6), Inches(0.6), Inches(8.5), Inches(1.0))
    tf = title_box.text_frame
    p = tf.paragraphs[0]
    p.text = body.title
    p.font.size = Pt(26)
    p.font.bold = True
    p.font.color.rgb = rgb(PRIMARY)
    p.alignment = PP_ALIGN.RIGHT

    if body.subtitle:
        sub_box = slide.shapes.add_textbox(Inches(0.6), Inches(1.3), Inches(8.5), Inches(0.6))
        tf2 = sub_box.text_frame
        p2 = tf2.paragraphs[0]
        p2.text = body.subtitle
        p2.font.size = Pt(14)
        p2.font.color.rgb = rgb(SECONDARY)
        p2.alignment = PP_ALIGN.RIGHT

    for spec in body.slides:
        slide = prs.slides.add_slide(prs.slide_layouts[6])

        header = slide.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(8.5), Inches(0.8))
        tfh = header.text_frame
        ph = tfh.paragraphs[0]
        ph.text = spec.title
        ph.font.size = Pt(24)
        ph.font.bold = True
        ph.font.color.rgb = rgb(PRIMARY)
        ph.alignment = PP_ALIGN.RIGHT

        if spec.bullets:
            box = slide.shapes.add_textbox(Inches(0.6), Inches(1.4), Inches(5.4), Inches(4.8))
            tfb = box.text_frame
            for i, bullet in enumerate(spec.bullets):
                p = tfb.paragraphs[0] if i == 0 else tfb.add_paragraph()
                p.text = bullet
                p.font.size = Pt(18)
                p.alignment = PP_ALIGN.RIGHT

        if spec.table_headers:
            rows = len(spec.table_rows) + 1
            cols = len(spec.table_headers)
            table_shape = slide.shapes.add_table(rows, cols, Inches(6.1), Inches(1.5), Inches(3.0), Inches(3.8))
            table = table_shape.table

            for c, header in enumerate(spec.table_headers):
                cell = table.cell(0, c)
                cell.text = str(header)
                cell.fill.solid()
                cell.fill.fore_color.rgb = rgb(PRIMARY)

            for r, row in enumerate(spec.table_rows, start=1):
                for c, value in enumerate(row):
                    table.cell(r, c).text = str(value)

    prs.save(str(output_path))

    return {
        "success": True,
        "file_name": file_name,
        "file_path": str(output_path),
        "export_dir": str(EXPORT_DIR),
    }
