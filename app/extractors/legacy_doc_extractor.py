"""Legacy .doc document extraction.

Primary approach: subprocess call to antiword (preferred) or catdoc.
Fallback: printable-ASCII binary text extraction.

Both antiword and catdoc are system utilities — install via apt:
    apt-get install antiword catdoc
"""

import os
import subprocess
import tempfile
from typing import Optional

from ..extractor import ExtractionResult
from .base import BaseExtractor


def _run_antiword(file_path: str) -> Optional[str]:
    """Try to extract text using antiword.

    Returns extracted text on success, None if antiword is unavailable
    or fails.
    """
    try:
        result = subprocess.run(
            ["antiword", file_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _run_catdoc(file_path: str) -> Optional[str]:
    """Try to extract text using catdoc.

    Returns extracted text on success, None if catdoc is unavailable
    or fails.
    """
    try:
        result = subprocess.run(
            ["catdoc", file_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _extract_binary_text(data: bytes) -> str:
    """Extract printable ASCII runs from binary data.

    Scans bytes for runs of printable ASCII characters (>=4 chars).
    This is an improved version of the binary text extraction found
    in document-conversion.service.ts lines 117-143.

    Printable characters considered: 0x20 (space) through 0x7E (~),
    plus tab (0x09), newline (0x0A), carriage return (0x0D).
    """
    runs: list[str] = []
    current_run: list[bytes] = []

    for byte in data:
        # Printable ASCII range, plus common whitespace
        if 0x20 <= byte <= 0x7E or byte in (0x09, 0x0A, 0x0D):
            current_run.append(bytes([byte]))
        else:
            if len(current_run) >= 4:
                runs.append(b"".join(current_run).decode("ascii", errors="replace"))
            current_run = []

    # Flush remaining run
    if len(current_run) >= 4:
        runs.append(b"".join(current_run).decode("ascii", errors="replace"))

    text = "\n".join(runs)

    # Clean up the extracted text
    lines: list[str] = []
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            lines.append(clean)

    return "\n".join(lines)


class LegacyDocExtractor(BaseExtractor):
    """Extractor for legacy .doc (Word 97-2003) documents.

    Extraction priority:
        1. antiword (best quality, handles most .doc files)
        2. catdoc (fallback CLI tool)
        3. Binary text extraction (low quality fallback)

    Returns reduced confidence for binary fallback.
    """

    def extract(self, data: bytes, filename: Optional[str] = None) -> ExtractionResult:
        """Extract text from a legacy .doc document.

        Args:
            data: Raw .doc file bytes.
            filename: Optional original filename.

        Returns:
            ExtractionResult with extracted text content.
        """
        temp_file = None
        try:
            # Write bytes to a temporary file for CLI tools
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".doc")
            temp_file.write(data)
            temp_path = temp_file.name
            temp_file.close()  # Close so CLI tools can open it on Windows

            # Try antiword first
            text = _run_antiword(temp_path)
            if text is not None:
                return self._build_result(text, confidence=0.6)

            # Then try catdoc
            text = _run_catdoc(temp_path)
            if text is not None:
                return self._build_result(text, confidence=0.6)

            # Fallback: binary text extraction
            text = _extract_binary_text(data)
            if text.strip():
                return self._build_result(text, confidence=0.3)

            # No text extracted
            return ExtractionResult(
                full_text="",
                confidence=0.05,
                requirements=[
                    "Could not extract text from legacy .doc format. "
                    "Install antiword or catdoc for better extraction."
                ],
            )

        finally:
            # Clean up temp file
            if temp_file is not None:
                try:
                    os.unlink(temp_path)
                except (OSError, PermissionError):
                    pass

    def _build_result(self, text: str, confidence: float) -> ExtractionResult:
        """Build an ExtractionResult from extracted text."""
        full_text = text.strip()
        char_count = len(full_text)

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
