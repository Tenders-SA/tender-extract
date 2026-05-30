"""ODT (OpenDocument Text) document extraction using odfpy.

Parses ODT XML content and extracts all paragraph text.
"""

from io import BytesIO
from typing import Optional

from ..extractor import ExtractionResult
from .base import BaseExtractor


class OdtExtractor(BaseExtractor):
    """Extractor for .odt (OpenDocument Text) documents.

    Uses odfpy (odf.text module) to parse ODT content and extract
    paragraph text from the document body.
    """

    def extract(self, data: bytes, filename: Optional[str] = None) -> ExtractionResult:
        """Extract text from an .odt document.

        Args:
            data: Raw .odt file bytes.
            filename: Optional original filename.

        Returns:
            ExtractionResult with extracted text content.
        """
        try:
            from odf import text as odf_text  # type: ignore[import-not-found]
            from odf.element import Element  # type: ignore[import-not-found]
            from odf.opendocument import load  # type: ignore[import-not-found]
        except ImportError:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["odfpy package is not installed"],
            )

        try:
            doc = load(BytesIO(data))
        except Exception:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["Failed to open ODT document"],
            )

        paragraphs: list[str] = []

        # Extract text from all paragraph elements in the document
        for para in doc.getElementsByType(odf_text.P):
            text = _get_element_text(para)
            if text.strip():
                paragraphs.append(text.strip())

        # Also extract headings (text:h elements)
        try:
            for heading in doc.getElementsByType(odf_text.H):
                text = _get_element_text(heading)
                if text.strip():
                    paragraphs.append(text.strip())
        except Exception:
            pass

        if not paragraphs:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["No text content found in ODT document"],
            )

        full_text = "\n".join(paragraphs)

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
        for para in paragraphs:
            if len(para) > 50:
                description = para
                break

        return ExtractionResult(
            full_text=full_text,
            description=description,
            confidence=confidence,
            raw_text_preview=full_text[:500] if full_text else None,
        )


def _get_element_text(element: object) -> str:
    """Recursively extract text from an ODF element and its children."""
    from odf.element import Element  # type: ignore[import-not-found]
    from odf.element import Text as OdfText  # type: ignore[import-not-found]
    from odf.namespaces import TEXTNS  # type: ignore[import-not-found]  # noqa: N812

    parts: list[str] = []

    if hasattr(element, "childNodes"):
        for child in element.childNodes:
            if child is None:
                continue
            if isinstance(child, str):
                parts.append(child)
            elif isinstance(child, OdfText):
                # ODF Text node — extract its data
                if hasattr(child, "data") and child.data:
                    parts.append(str(child.data))
            elif hasattr(child, "tagName"):
                # Element nodes (spans, runs, etc.) — recurse
                parts.append(_get_element_text(child))
            elif hasattr(child, "data"):
                parts.append(str(child.data))

    return "".join(parts)
