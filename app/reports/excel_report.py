
from typing import Dict, Any
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.utils import get_column_letter

from app.config import EXPORT_DIR
from app.schemas.report_requests import SaveExcelReportRequest
from app.utils.files import sanitize_file_name
from app.design.theme import POWERBI_THEME


def save_excel_report_local(body: SaveExcelReportRequest) -> Dict[str, Any]:
    if not body.sheets:
        return {"success": False, "message": "At least one sheet is required."}

    wb = Workbook()
    first = True

    thin = Side(style="thin", color="D9D9D9")

    for sheet_spec in body.sheets:
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = (sheet_spec.name or "Sheet")[:31]
        ws.sheet_view.rightToLeft = True
        ws.freeze_panes = "A2"
        ws.sheet_properties.tabColor = POWERBI_THEME["primary"].replace("#", "")

        row_idx = 1

        if body.title and ws.title == (body.sheets[0].name or "Sheet1")[:31]:
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(1, len(sheet_spec.headers)))
            cell = ws.cell(row=1, column=1, value=body.title)
            cell.font = Font(bold=True, size=16, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor=POWERBI_THEME["primary"].replace("#", ""))
            cell.alignment = Alignment(horizontal="right", vertical="center")
            row_idx = 3

        header_row_index = row_idx

        for col_idx, header in enumerate(sheet_spec.headers, start=1):
            cell = ws.cell(row=header_row_index, column=col_idx, value=header)
            cell.fill = PatternFill("solid", fgColor=POWERBI_THEME["secondary"].replace("#", ""))
            cell.font = Font(color="FFFFFF", bold=True, size=11)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)

        data_start = header_row_index + 1
        for r, values in enumerate(sheet_spec.rows, start=data_start):
            for c, value in enumerate(values, start=1):
                cell = ws.cell(row=r, column=c, value=value)
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)

                if r % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor="F8FBFF")

        if sheet_spec.headers and sheet_spec.rows:
            end_col = get_column_letter(len(sheet_spec.headers))
            table_ref = f"A{header_row_index}:{end_col}{header_row_index + len(sheet_spec.rows)}"
            table = Table(displayName=f"Table_{abs(hash(ws.title)) % 100000}", ref=table_ref)
            style = TableStyleInfo(
                name="TableStyleMedium2",
                showFirstColumn=False,
                showLastColumn=False,
                showRowStripes=True,
                showColumnStripes=False,
            )
            table.tableStyleInfo = style
            ws.add_table(table)

        widths = {}
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
            for cell in row:
                val = "" if cell.value is None else str(cell.value)
                widths[cell.column] = max(widths.get(cell.column, 10), min(len(val) + 4, 35))

        for col_idx, width in widths.items():
            ws.column_dimensions[get_column_letter(col_idx)].width = width

    file_name = sanitize_file_name(body.file_name, "report", "xlsx")
    output_path = EXPORT_DIR / file_name
    wb.save(output_path)

    return {
        "success": True,
        "file_name": file_name,
        "file_path": str(output_path),
        "export_dir": str(EXPORT_DIR),
    }
