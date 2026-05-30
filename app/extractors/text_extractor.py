"""CSV and TXT document extraction using stdlib.

For .csv files: uses csv.reader to parse and format as tabular text.
For .txt files: detects encoding (UTF-8 BOM, UTF-8, latin-1 fallback).
"""

import csv
import io
from typing import Optional

from ..extractor import ExtractionResult
from .base import BaseExtractor


class TextExtractor(BaseExtractor):
    """Extractor for .csv and .txt files.

    Uses stdlib for all processing — no external dependencies needed.
    CSV files are formatted as tabular text with column headers.
    """

    def extract(self, data: bytes, filename: Optional[str] = None) -> ExtractionResult:
        """Extract text from a .csv or .txt file.

        Args:
            data: Raw file bytes.
            filename: Optional original filename — used to detect CSV vs TXT.

        Returns:
            ExtractionResult with extracted text content.
        """
        is_csv = _looks_like_csv(filename, data)

        if is_csv:
            return self._extract_csv(data)
        else:
            return self._extract_text(data)

    # ------------------------------------------------------------------
    # CSV extraction
    # ------------------------------------------------------------------

    def _extract_csv(self, data: bytes) -> ExtractionResult:
        """Parse CSV bytes and format as tabular text."""
        # Detect encoding
        text = _decode_bytes(data)
        if text is None:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["Could not decode CSV file"],
            )

        try:
            reader = csv.reader(io.StringIO(text))
            rows = list(reader)
        except Exception:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["Failed to parse CSV file"],
            )

        if not rows:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["CSV file is empty"],
            )

        output_parts: list[str] = []

        # Header row (if it looks like a header)
        if rows[0]:
            output_parts.append(" | ".join(rows[0]))
            output_parts.append("-" * min(80, len(" | ".join(rows[0]))))

        # Data rows
        for row in rows[1:]:
            if row:
                output_parts.append(" | ".join(row))

        full_text = "\n".join(output_parts)
        row_count = len(rows) - 1 if len(rows) > 1 else 0

        # Confidence: 0.5 base for CSV (structured but limited semantics)
        if row_count >= 10:
            confidence = 0.5
        elif row_count >= 3:
            confidence = 0.4
        elif row_count >= 1:
            confidence = 0.3
        else:
            confidence = 0.1

        # Description: first row content
        description = ""
        if len(rows) > 0 and rows[0]:
            col_count = len(rows[0])
            description = f"CSV file with {len(rows)} rows, {col_count} columns"
        if len(rows) > 0:
            first_data = " | ".join(rows[0])[:200]
            if first_data:
                description = f"{description}: {first_data}" if description else first_data

        return ExtractionResult(
            full_text=full_text,
            description=description,
            confidence=confidence,
            raw_text_preview=full_text[:500] if full_text else None,
        )

    # ------------------------------------------------------------------
    # Plain text extraction
    # ------------------------------------------------------------------

    def _extract_text(self, data: bytes) -> ExtractionResult:
        """Extract plain text from bytes with encoding detection."""
        text = _decode_bytes(data)

        if text is None:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["Could not decode text file"],
            )

        full_text = text.strip()

        if not full_text:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["Text file is empty"],
            )

        char_count = len(full_text)

        # Confidence for plain text: 0.8 base
        if char_count >= 500:
            confidence = 0.8
        elif char_count >= 100:
            confidence = 0.6
        elif char_count >= 20:
            confidence = 0.4
        else:
            confidence = 0.2

        # Description: first meaningful line
        description = ""
        for line in full_text.splitlines():
            clean = line.strip()
            if len(clean) > 50:
                description = clean
                break
        if not description and full_text:
            description = full_text[:200]

        return ExtractionResult(
            full_text=full_text,
            description=description,
            confidence=confidence,
            raw_text_preview=full_text[:500] if full_text else None,
        )


# ------------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------------


def _looks_like_csv(filename: Optional[str], data: bytes) -> bool:
    """Determine if the content looks like a CSV file.

    Checks filename extension first, then content heuristics.
    """
    if filename:
        ext = _get_extension(filename)
        if ext == ".csv":
            return True

    # Content heuristic: first 4096 bytes look like CSV
    head = data[:4096]
    try:
        decoded = head.decode("utf-8", errors="replace")
    except Exception:
        return False

    # Count commas vs other delimiters in first line
    lines = decoded.splitlines()
    if not lines:
        return False

    first_line = lines[0].strip()
    if not first_line:
        return False

    comma_count = first_line.count(",")
    pipe_count = first_line.count("|")
    tab_count = first_line.count("\t")
    semicolon_count = first_line.count(";")

    # CSV typically has multiple commas per line
    total_delimiters = comma_count + pipe_count + tab_count + semicolon_count
    if total_delimiters >= 2 and comma_count >= total_delimiters * 0.5:
        return True

    return False


def _get_extension(filename: str) -> str:
    """Extract lowercase file extension from a filename."""
    idx = filename.rfind(".")
    if idx >= 0:
        return filename[idx:].lower()
    return ""


def _decode_bytes(data: bytes) -> Optional[str]:
    """Decode bytes to string with encoding detection.

    Priority: UTF-8 BOM -> UTF-8 -> latin-1 -> replace-based fallback.
    """
    # UTF-8 with BOM
    if data[:3] == b"\xef\xbb\xbf":
        try:
            return data[3:].decode("utf-8")
        except UnicodeDecodeError:
            pass

    # UTF-8
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # Latin-1 (ISO 8859-1) — accepts all byte values
    try:
        return data.decode("latin-1")
    except UnicodeDecodeError:
        pass

    # Last resort: UTF-8 with replacement
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return None
