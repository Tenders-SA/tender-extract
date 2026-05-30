"""Abstract base class for all document extractors.

All format-specific extractors (PDF, DOCX, XLSX, ZIP, etc.) must implement
the BaseExtractor interface to be registered in the ExtractorRegistry.
"""

from abc import ABC, abstractmethod
from typing import Optional

# Import shared data types from the parent extractor module
from ..extractor import ExtractionResult


class BaseExtractor(ABC):
    """Abstract base for all document extractors.

    Every extractor must implement extract(data, filename?) returning an
    ExtractionResult with the same schema. This enables the ExtractorRegistry
    to dispatch any supported document type through the same interface.
    """

    @abstractmethod
    def extract(self, data: bytes, filename: Optional[str] = None) -> ExtractionResult:
        """Extract structured content from raw document bytes.

        Args:
            data: Raw bytes of the document to extract.
            filename: Optional original filename (used for extension hints).

        Returns:
            ExtractionResult with extracted fields. At minimum, full_text
            should be populated with all readable text content.

        Raises:
            UnsearchablePDF: If the document has too little searchable text.
            ValueError: If the document format cannot be recognised.
        """
        ...
