"""XLS (Excel 97-2003) document extraction using xlrd.

Extracts text content from all sheets, rows, and cells.
Handles .xls format quirks (dates as floats, etc.).

NOTE: xlrd only supports .xls files, NOT .xlsx.
"""

from io import BytesIO
from typing import Optional

from ..extractor import ExtractionResult
from .base import BaseExtractor


class XlsExtractor(BaseExtractor):
    """Extractor for legacy .xls (Excel 97-2003) spreadsheets.

    Uses xlrd to iterate all sheets, rows, and cells, extracting
    text content formatted as:
        [Sheet: SheetName]
        Cell A1: value
        Cell A2: value
    """

    def extract(self, data: bytes, filename: Optional[str] = None) -> ExtractionResult:
        """Extract text from a legacy .xls spreadsheet.

        Args:
            data: Raw .xls file bytes.
            filename: Optional original filename.

        Returns:
            ExtractionResult with extracted text content.
        """
        try:
            import xlrd  # type: ignore[import-not-found]
        except ImportError:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["xlrd package is not installed"],
            )

        try:
            wb = xlrd.open_workbook(file_contents=data)
        except Exception:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["Failed to open XLS workbook"],
            )

        all_text_parts: list[str] = []
        total_cells = 0
        populated_cells = 0

        for sheet_idx in range(wb.nsheets):
            ws = wb.sheet_by_index(sheet_idx)
            sheet_parts: list[str] = []
            sheet_populated = 0

            for row_idx in range(ws.nrows):
                for col_idx in range(ws.ncols):
                    total_cells += 1
                    cell = ws.cell(row_idx, col_idx)
                    cell_value = cell.value
                    cell_type = cell.ctype

                    if cell_value is None or cell_value == "":
                        continue

                    # Convert cell value to string
                    if cell_type == xlrd.XL_CELL_DATE:
                        # Try to convert date tuple to readable string
                        try:
                            date_tuple = xlrd.xldate_as_tuple(cell_value, wb.datemode)
                            # Format as YYYY-MM-DD or full datetime
                            if date_tuple[3:] == (0, 0, 0):
                                cell_str = f"{date_tuple[0]:04d}-{date_tuple[1]:02d}-{date_tuple[2]:02d}"
                            else:
                                cell_str = (
                                    f"{date_tuple[0]:04d}-{date_tuple[1]:02d}-{date_tuple[2]:02d} "
                                    f"{date_tuple[3]:02d}:{date_tuple[4]:02d}:{date_tuple[5]:02d}"
                                )
                        except Exception:
                            cell_str = str(cell_value)
                    elif cell_type == xlrd.XL_CELL_BOOLEAN:
                        cell_str = "TRUE" if cell_value else "FALSE"
                    elif cell_type == xlrd.XL_CELL_ERROR:
                        cell_str = xlrd.error_text_from_code.get(cell_value, f"ERROR({cell_value})")
                    else:
                        cell_str = str(cell_value)

                    cell_str = cell_str.strip()
                    if cell_str:
                        sheet_populated += 1
                        populated_cells += 1
                        col_letter = _col_letter(col_idx)
                        sheet_parts.append(f"Cell {col_letter}{row_idx + 1}: {cell_str}")

            if sheet_parts:
                all_text_parts.append(f"[Sheet: {ws.name}]")
                all_text_parts.extend(sheet_parts)

        if not all_text_parts:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["No data found in XLS workbook"],
            )

        full_text = "\n".join(all_text_parts)

        # Confidence based on content volume
        if populated_cells == 0:
            confidence = 0.0
        elif total_cells == 0:
            confidence = 0.0
        else:
            ratio = populated_cells / max(total_cells, 1)
            if ratio >= 0.5 and populated_cells >= 20:
                confidence = 0.7
            elif populated_cells >= 10:
                confidence = 0.5
            elif populated_cells >= 3:
                confidence = 0.3
            else:
                confidence = 0.1

        # Description: first meaningful content
        description = ""
        for line in full_text.splitlines():
            if line.startswith("Cell ") and len(line) > 60:
                description = line
                break

        return ExtractionResult(
            full_text=full_text,
            description=description,
            confidence=confidence,
            raw_text_preview=full_text[:500] if full_text else None,
        )


def _col_letter(col_idx: int) -> str:
    """Convert a zero-based column index to an Excel column letter.

    Examples:
        0 -> 'A', 1 -> 'B', 25 -> 'Z', 26 -> 'AA', 27 -> 'AB'
    """
    result = ""
    while col_idx >= 0:
        result = chr(ord("A") + col_idx % 26) + result
        col_idx = col_idx // 26 - 1
    return result
