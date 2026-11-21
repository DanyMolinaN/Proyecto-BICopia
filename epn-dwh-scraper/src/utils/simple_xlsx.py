"""
Generador nativo de archivos Microsoft Excel (.xlsx) sin dependencias externas.

Implementa el estándar OpenXML (ECMA-376) utilizando únicamente módulos de la biblioteca
estándar de Python (zipfile, xml.sax.saxutils). Permite exportar DataFrames y listas de diccionarios
a archivos .xlsx completamente compatibles con Excel, LibreOffice y Google Sheets.
"""

from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Union
from xml.sax.saxutils import escape
import zipfile
import pandas as pd


def _col_name(n: int) -> str:
    """Convierte un índice de columna 0-based a letra de Excel (0 -> A, 27 -> AB)."""
    name = ""
    n += 1
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        name = chr(65 + remainder) + name
    return name


def create_xlsx(
    sheets: Dict[str, Union[pd.DataFrame, List[Dict[str, Any]]]],
    output_path: Union[str, Path],
) -> Path:
    """Genera un archivo Excel (.xlsx) con una o más hojas a partir de DataFrames o listas.

    Args:
        sheets: Diccionario {nombre_hoja: DataFrame_o_lista_de_diccionarios}.
        output_path: Ruta destino del archivo .xlsx.

    Returns:
        Path: Ruta del archivo generado.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Convertir listas a DataFrames si es necesario
    normalized_sheets: Dict[str, pd.DataFrame] = {}
    for name, data in sheets.items():
        if isinstance(data, pd.DataFrame):
            normalized_sheets[name] = data
        else:
            normalized_sheets[name] = pd.DataFrame(data)

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # 1. [Content_Types].xml
        types_lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
            '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
            '  <Default Extension="xml" ContentType="application/xml"/>',
            '  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
            '  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        ]
        for idx in range(1, len(normalized_sheets) + 1):
            types_lines.append(
                f'  <Override PartName="/xl/worksheets/sheet{idx}.xml" '
                f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
        types_lines.append("</Types>")
        z.writestr("[Content_Types].xml", "\n".join(types_lines))

        # 2. _rels/.rels
        rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>\n'
            '</Relationships>'
        )
        z.writestr("_rels/.rels", rels)

        # 3. xl/_rels/workbook.xml.rels
        wb_rels_lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
        ]
        sheet_names = list(normalized_sheets.keys())
        for idx in range(1, len(sheet_names) + 1):
            wb_rels_lines.append(
                f'  <Relationship Id="rId{idx}" '
                f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{idx}.xml"/>'
            )
        styles_rid = len(sheet_names) + 1
        wb_rels_lines.append(
            f'  <Relationship Id="rId{styles_rid}" '
            f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            f'Target="styles.xml"/>'
        )
        wb_rels_lines.append("</Relationships>")
        z.writestr("xl/_rels/workbook.xml.rels", "\n".join(wb_rels_lines))

        # 4. xl/workbook.xml
        wb_lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
            "  <sheets>",
        ]
        for idx, sheet_name in enumerate(sheet_names, start=1):
            safe_sheet_name = escape(sheet_name[:31])
            wb_lines.append(f'    <sheet name="{safe_sheet_name}" sheetId="{idx}" r:id="rId{idx}"/>')
        wb_lines.append("  </sheets>")
        wb_lines.append("</workbook>")
        z.writestr("xl/workbook.xml", "\n".join(wb_lines))

        # 5. xl/styles.xml
        styles = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">\n'
            '  <fonts count="2">\n'
            '    <font><sz val="11"/><name val="Calibri"/></font>\n'
            '    <font><b/><sz val="11"/><name val="Calibri"/></font>\n'
            '  </fonts>\n'
            '  <fills count="2">\n'
            '    <fill><patternFill patternType="none"/></fill>\n'
            '    <fill><patternFill patternType="gray125"/></fill>\n'
            '  </fills>\n'
            '  <borders count="1">\n'
            '    <border><left/><right/><top/><bottom/></border>\n'
            '  </borders>\n'
            '  <cellStyleXfs count="1">\n'
            '    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>\n'
            '  </cellStyleXfs>\n'
            '  <cellXfs count="2">\n'
            '    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>\n'
            '    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>\n'
            '  </cellXfs>\n'
            '</styleSheet>'
        )
        z.writestr("xl/styles.xml", styles)

        # 6. xl/worksheets/sheet{i}.xml
        for idx, (sheet_name, df) in enumerate(normalized_sheets.items(), start=1):
            sheet_lines = [
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
                "  <sheetData>",
            ]
            # Encabezados (fila 1, estilo bold = s="1")
            sheet_lines.append('    <row r="1">')
            for col_idx, col_name in enumerate(df.columns):
                cell_ref = f"{_col_name(col_idx)}1"
                val = escape(str(col_name))
                sheet_lines.append(f'      <c r="{cell_ref}" t="inlineStr" s="1"><is><t>{val}</t></is></c>')
            sheet_lines.append("    </row>")

            # Filas de datos (fila 2 en adelante)
            for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
                sheet_lines.append(f'    <row r="{row_idx}">')
                for col_idx, col_name in enumerate(df.columns):
                    cell_ref = f"{_col_name(col_idx)}{row_idx}"
                    cell_val = row[col_name]
                    if cell_val is None or pd.isna(cell_val):
                        continue
                    if isinstance(cell_val, (int, float)) and not isinstance(cell_val, bool):
                        sheet_lines.append(f'      <c r="{cell_ref}"><v>{cell_val}</v></c>')
                    else:
                        val = escape(str(cell_val))
                        sheet_lines.append(f'      <c r="{cell_ref}" t="inlineStr"><is><t>{val}</t></is></c>')
                sheet_lines.append("    </row>")

            sheet_lines.append("  </sheetData>")
            sheet_lines.append("</worksheet>")
            z.writestr(f"xl/worksheets/sheet{idx}.xml", "\n".join(sheet_lines))

    out.write_bytes(buf.getvalue())
    return out
