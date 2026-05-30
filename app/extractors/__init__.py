"""ExtractorRegistry — maps file extensions and MIME types to BaseExtractor classes.

Usage:
    from app.extractors import ExtractorRegistry, BaseExtractor

    # Automatic dispatch based on content sniffing, extension, or MIME type
    extractor = ExtractorRegistry.get_extractor(data, filename='tender.pdf')
    result = extractor.extract(data, filename='tender.pdf')

    # Or get an extractor by known type
    extractor = ExtractorRegistry.get_extractor(data, mime_type='application/pdf')
"""

import struct
from io import BytesIO
from typing import Optional

from .base import BaseExtractor


class ExtractorRegistry:
    """Registry mapping file extensions and MIME types to extractor classes.

    Detection priority:
        1. Magic byte / content sniffing (e.g. ZIP header PK\x03\x04)
        2. File extension (from filename parameter)
        3. MIME type (e.g. from Content-Type header)

    Extractor classes are imported lazily (only when first needed).
    """

    # Mapping of lowercase file extensions to extractor classes.
    # Lazy-load pattern: values are strings for deferred import resolution.
    EXTENSION_MAP: dict[str, str] = {
        '.pdf': 'PdfExtractor',
        '.docx': 'DocxExtractor',
        '.doc': 'LegacyDocExtractor',
        '.xlsx': 'XlsxExtractor',
        '.xls': 'XlsExtractor',
        '.pptx': 'PptxExtractor',
        '.odt': 'OdtExtractor',
        '.rtf': 'RtfExtractor',
        '.csv': 'TextExtractor',
        '.txt': 'TextExtractor',
        '.zip': 'ZipExtractor',
    }

    # Mapping of MIME types to extractor classes.
    MIME_MAP: dict[str, str] = {
        'application/pdf': 'PdfExtractor',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DocxExtractor',
        'application/msword': 'LegacyDocExtractor',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'XlsxExtractor',
        'application/vnd.ms-excel': 'XlsExtractor',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PptxExtractor',
        'application/vnd.oasis.opendocument.text': 'OdtExtractor',
        'application/rtf': 'RtfExtractor',
        'text/rtf': 'RtfExtractor',
        'text/csv': 'TextExtractor',
        'text/plain': 'TextExtractor',
        'application/zip': 'ZipExtractor',
        'application/x-zip-compressed': 'ZipExtractor',
    }

    # Magic byte signatures for content sniffing.
    # Format: (offset, magic_bytes, extractor_class_name)
    _MAGIC_SIGNATURES: list[tuple[int, bytes, str]] = [
        (0, b'PK\x03\x04', 'ZipExtractor'),          # ZIP / DOCX / XLSX / PPTX
        (0, b'%PDF', 'PdfExtractor'),                 # PDF
        (0, b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1', 'LegacyDocExtractor'),  # CFB (DOC / XLS / PPT)
    ]

    # Maps extractor class name -> actual module path for lazy loading
    _EXTRACTOR_MODULES: dict[str, tuple[str, str]] = {
        'PdfExtractor': ('app.extractors.pdf_extractor', 'PdfExtractor'),
        'DocxExtractor': ('app.extractors.docx_extractor', 'DocxExtractor'),
        'LegacyDocExtractor': ('app.extractors.legacy_doc_extractor', 'LegacyDocExtractor'),
        'XlsxExtractor': ('app.extractors.xlsx_extractor', 'XlsxExtractor'),
        'XlsExtractor': ('app.extractors.xls_extractor', 'XlsExtractor'),
        'PptxExtractor': ('app.extractors.pptx_extractor', 'PptxExtractor'),
        'OdtExtractor': ('app.extractors.odt_extractor', 'OdtExtractor'),
        'RtfExtractor': ('app.extractors.rtf_extractor', 'RtfExtractor'),
        'TextExtractor': ('app.extractors.text_extractor', 'TextExtractor'),
        'ZipExtractor': ('app.extractors.zip_extractor', 'ZipExtractor'),
    }

    # Cache for loaded extractor classes (singleton-like, one class object per type)
    _class_cache: dict[str, type[BaseExtractor]] = {}

    @classmethod
    def _get_extractor_class(cls, class_name: str) -> Optional[type[BaseExtractor]]:
        """Lazily import and cache an extractor class by its name.

        Returns None if the extractor module is not yet installed or
        the class is not found (e.g. when format support is added later).
        """
        if class_name in cls._class_cache:
            return cls._class_cache.get(class_name)

        module_path, attr_name = cls._EXTRACTOR_MODULES.get(class_name, (None, None))
        if module_path is None:
            return None

        import importlib
        try:
            module = importlib.import_module(module_path)
            extractor_class = getattr(module, attr_name)
        except (ModuleNotFoundError, ImportError, AttributeError):
            # Extractor module not yet available (future Phase 2+ format support)
            return None

        cls._class_cache[class_name] = extractor_class
        return extractor_class

    @classmethod
    def get_extractor(
        cls,
        data: bytes,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> Optional[BaseExtractor]:
        """Detect document type and return the appropriate BaseExtractor.

        Priority chain:
            1. Magic byte / content sniffing (most reliable)
            2. File extension from filename
            3. MIME type (least reliable)

        Returns None if the document type cannot be determined or if the
        corresponding extractor module is not yet installed.
        """
        # Priority 1: Magic byte / content sniffing
        class_name = cls._detect_by_magic(data)
        if class_name:
            extractor_class = cls._get_extractor_class(class_name)
            if extractor_class is not None:
                return extractor_class()

        # Priority 2: File extension
        if filename:
            ext = cls._get_extension(filename)
            class_name = cls.EXTENSION_MAP.get(ext)
            if class_name:
                extractor_class = cls._get_extractor_class(class_name)
                if extractor_class is not None:
                    return extractor_class()

        # Priority 3: MIME type
        if mime_type:
            normalized = mime_type.lower().split(';')[0].strip()
            class_name = cls.MIME_MAP.get(normalized)
            if class_name:
                extractor_class = cls._get_extractor_class(class_name)
                if extractor_class is not None:
                    return extractor_class()

        return None

    @classmethod
    def _detect_by_magic(cls, data: bytes) -> Optional[str]:
        """Detect document type by magic byte signature."""
        for offset, magic, class_name in cls._MAGIC_SIGNATURES:
            sniff = data[offset:offset + len(magic)]
            if sniff == magic:
                return class_name
        return None

    @staticmethod
    def _get_extension(filename: str) -> str:
        """Extract lowercase file extension from a filename."""
        idx = filename.rfind('.')
        if idx >= 0:
            return filename[idx:].lower()
        return ''
