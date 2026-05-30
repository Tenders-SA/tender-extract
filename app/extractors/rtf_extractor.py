"""RTF (Rich Text Format) document extraction using striprtf.

Converts RTF content to plaintext using the striprtf library.
"""

from typing import Optional

from ..extractor import ExtractionResult
from .base import BaseExtractor


class RtfExtractor(BaseExtractor):
    """Extractor for .rtf (Rich Text Format) documents.

    Uses striprtf to convert RTF markup to plain text. Handles
    common RTF formatting, character sets, and encodings.
    """

    def extract(self, data: bytes, filename: Optional[str] = None) -> ExtractionResult:
        """Extract text from an .rtf document.

        Args:
            data: Raw .rtf file bytes.
            filename: Optional original filename.

        Returns:
            ExtractionResult with extracted text content.
        """
        try:
            from striprtf.striprtf import rtf_to_text  # type: ignore[import-not-found]
        except ImportError:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["striprtf package is not installed"],
            )

        # Try UTF-8 first, fall back to latin-1
        try:
            rtf_text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                rtf_text = data.decode("latin-1")
            except UnicodeDecodeError:
                return ExtractionResult(
                    full_text="",
                    confidence=0.0,
                    requirements=["Could not decode RTF document text"],
                )

        try:
            text = rtf_to_text(rtf_text)
        except Exception:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["Failed to parse RTF document"],
            )

        if not text or not text.strip():
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["No text content found in RTF document"],
            )

        full_text = text.strip()

        # Confidence based on text length
        char_count = len(full_text)
        if char_count >= 500:
            confidence = 0.7
        elif char_count >= 100:
            confidence = 0.5
        else:
            confidence = 0.3

        # Description: first meaningful paragraph
        description = ""
        for line in full_text.splitlines():
            clean = line.strip()
            if len(clean) > 50:
                description = clean
                break

        return ExtractionResult(
            full_text=full_text,
            description=description,
            confidence=confidence,
            raw_text_preview=full_text[:500] if full_text else None,
        )
