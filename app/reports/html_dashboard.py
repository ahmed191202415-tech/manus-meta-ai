
from typing import Dict, Any
from html import escape

from app.config import EXPORT_DIR
from app.schemas.report_requests import SaveHtmlDashboardRequest
from app.utils.files import sanitize_file_name


def save_html_dashboard_local(body: SaveHtmlDashboardRequest) -> Dict[str, Any]:
    file_name = sanitize_file_name(body.file_name, "dashboard", "html")
    output_path = EXPORT_DIR / file_name

    kpi_cards = ""
    for item in body.kpis:
        label = escape(str(item.get("label", "")))
        value = escape(str(item.get("value", "")))
        color = escape(str(item.get("color", "#1F4E78")))
        kpi_cards += f'''
        <div class="card">
            <div class="label">{label}</div>
            <div class="value" style="color:{color}">{value}</div>
        </div>
        '''

    sections_html = ""
    for section in body.sections:
        heading = f"<h2>{escape(section.heading)}</h2>" if section.heading else ""
        paragraphs = "".join(f"<p>{escape(p)}</p>" for p in section.paragraphs)

        table_html = ""
        if section.table_headers:
            headers = "".join(f"<th>{escape(str(h))}</th>" for h in section.table_headers)
            rows = ""
            for row in section.table_rows:
                rows += "<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in row) + "</tr>"
            table_html = f"<table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>"

        sections_html += f'<section class="section">{heading}{paragraphs}{table_html}</section>'

    html = f'''<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>{escape(body.title)}</title>
<style>
body {{
    font-family: Arial, sans-serif;
    background: #f5f7fb;
    margin: 0;
    padding: 0;
    direction: rtl;
    color: #1f1f1f;
}}
.container {{
    max-width: 1280px;
    margin: 0 auto;
    padding: 24px;
}}
.header {{
    background: linear-gradient(135deg, #1F4E78, #2F75B5);
    color: white;
    border-radius: 18px;
    padding: 28px;
    margin-bottom: 22px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.08);
}}
h1 {{
    margin: 0 0 8px 0;
    font-size: 34px;
}}
.subtitle {{
    opacity: 0.92;
}}
.kpis {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 18px;
    margin-bottom: 22px;
}}
.card {{
    background: white;
    border-radius: 18px;
    padding: 22px;
    box-shadow: 0 4px 18px rgba(0,0,0,0.08);
    border: 1px solid #E9EEF7;
}}
.label {{
    color: #666;
    font-size: 14px;
    margin-bottom: 10px;
}}
.value {{
    font-size: 30px;
    font-weight: 700;
}}
.section {{
    background: white;
    border-radius: 18px;
    padding: 22px;
    margin-bottom: 22px;
    box-shadow: 0 4px 18px rgba(0,0,0,0.08);
    border: 1px solid #E9EEF7;
}}
h2 {{
    margin-top: 0;
    color: #1F4E78;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 14px;
    overflow: hidden;
    border-radius: 12px;
}}
th, td {{
    border: 1px solid #E7ECF3;
    padding: 10px 12px;
    text-align: right;
}}
th {{
    background: #1F4E78;
    color: white;
}}
tr:nth-child(even) td {{
    background: #FAFCFF;
}}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>{escape(body.title)}</h1>
        <div class="subtitle">{escape(body.subtitle or "")}</div>
    </div>

    <div class="kpis">
        {kpi_cards}
    </div>

    {sections_html}
</div>
</body>
</html>'''

    output_path.write_text(html, encoding="utf-8")

    return {
        "success": True,
        "file_name": file_name,
        "file_path": str(output_path),
        "export_dir": str(EXPORT_DIR),
    }
