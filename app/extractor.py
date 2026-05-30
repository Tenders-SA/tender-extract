"""Enhanced PDF extraction for South African tender documents.

Deterministic, fast, SA-specific.

NOTE: As of Phase 1 of the Unified Document Extraction refactoring, the
      PDF-specific extraction logic has been moved to:
          app/extractors/pdf_extractor.py (PdfExtractor)

      This module now:
      - Defines shared data types used by all format extractors
      - Provides the TenderExtractor class for backward compatibility
      - Re-exports extraction types so existing consumers (main.py) still work

      The TenderExtractor.extract() method now delegates to PdfExtractor
      internally. All PDF-specific patterns and methods live in PdfExtractor.

      For new code, use:
          from app.extractors.pdf_extractor import PdfExtractor
          extractor = PdfExtractor()
          result = extractor.extract(pdf_bytes)

      For backward compatibility:
          from .extractor import TenderExtractor
          extractor = TenderExtractor()
          result = extractor.extract(pdf_bytes)
"""

import re
from dataclasses import dataclass, field
from typing import Optional


class UnsearchablePDF(Exception):
    """Raised when a PDF has too little searchable text."""
    pass


class DocType:
    """Document type classification constants."""
    RFQ = "RFQ"
    TENDER = "TENDER"
    EOI = "EOI"
    RFP = "RFP"
    UNKNOWN = "unknown"


@dataclass
class EvaluationSubCriterion:
    """A single evaluation sub-criterion with point weight."""
    criterion: str = ""
    weight: int = 0


@dataclass
class EvaluationCriteria:
    """Structured evaluation criteria."""
    system: Optional[str] = None
    functionality_threshold: Optional[str] = None
    sub_criteria: list[EvaluationSubCriterion] = field(default_factory=list)
    details: Optional[str] = None


@dataclass
class ContactInfo:
    """Extracted contact information."""
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    department: Optional[str] = None
    address: Optional[str] = None


@dataclass
class BriefingSession:
    """Briefing session or site visit details."""
    date: Optional[str] = None
    time: Optional[str] = None
    venue: Optional[str] = None
    is_compulsory: bool = False


@dataclass
class BBBEEInfo:
    """B-BBEE / preference-point information."""
    minimum_level: Optional[str] = None
    points_allocation: Optional[str] = None
    details: Optional[str] = None
    local_content_requirement: Optional[str] = None
    hdi_requirement: Optional[str] = None
    preferential_procurement: Optional[str] = None
    preference_points_system: Optional[str] = None


@dataclass
class ExtractionResult:
    """Comprehensive tender extraction result.

    Used by all format extractors (PDF, DOCX, XLSX, ZIP, etc.) as the
    unified output dataclass. Every extractor must populate this regardless
    of the source document format.
    """
    description: str = ""
    requirements: list[str] = field(default_factory=list)

    tender_number: Optional[str] = None
    title: Optional[str] = None

    closing_date: Optional[str] = None
    closing_time: Optional[str] = None
    publication_date: Optional[str] = None
    validity_period: Optional[str] = None
    contract_period: Optional[str] = None

    issuing_organization: Optional[str] = None
    department: Optional[str] = None

    delivery_location: Optional[str] = None
    submission_address: Optional[str] = None

    estimated_value: Optional[str] = None
    bid_bond_required: Optional[str] = None
    payment_terms: Optional[str] = None

    bbbee: Optional[BBBEEInfo] = None
    contact: Optional[ContactInfo] = None
    briefing_session: Optional[BriefingSession] = None

    evaluation_criteria: Optional[str] = None
    special_conditions: Optional[str] = None
    returnable_documents: list[str] = field(default_factory=list)

    # Phase 1 extraction enhancements
    document_type: str = DocType.UNKNOWN
    province: Optional[str] = None
    contract_type: Optional[str] = None
    procurement_threshold: Optional[str] = None
    evaluation_structured: Optional[EvaluationCriteria] = None

    confidence: float = 0.0
    pages_used: list[int] = field(default_factory=list)
    raw_text_preview: Optional[str] = None
    full_text: str = ""

    # Internal signal. This is not currently exposed by schemas.py/main.py.
    scanned_pages_detected: bool = False

    @property
    def needs_ai_fallback(self) -> bool:
        """True if deterministic extraction is weak enough to justify AI fallback.

        Document-type-aware threshold: RFQs naturally have less structured content
        so they use a lower confidence threshold (0.40) vs standard (0.55).
        """
        generic_requirements = (
            not self.requirements
            or self.requirements == ["No specific requirements found"]
            or self.requirements == ["Insufficient searchable text - AI extraction recommended"]
        )

        threshold = 0.40 if self.document_type == DocType.RFQ else 0.55

        return (
            self.confidence < threshold
            or not self.tender_number
            or not self.closing_date
            or not self.title
            or not self.issuing_organization
            or len(self.description or "") < 50
            or generic_requirements
        )


class TenderExtractor:
    """Backward-compatible wrapper for PdfExtractor.

    This class maintains the original TenderExtractor API so that existing
    consumers in main.py continue to work without modification. It delegates
    all PDF extraction to PdfExtractor internally.

    The original regex patterns and extraction methods have been moved to
        app/extractors/pdf_extractor.py (PdfExtractor).

    For new code, use PdfExtractor directly:
        from app.extractors.pdf_extractor import PdfExtractor
    """

    def extract(self, pdf_bytes: bytes) -> ExtractionResult:
        """Extract tender information from PDF bytes.

        Delegates to PdfExtractor internally for all PDF-specific logic.
        """
        from .extractors.pdf_extractor import PdfExtractor as _PdfExtractor

        extractor = _PdfExtractor()
        return extractor.extract(pdf_bytes)

    def contains_scanned_pages(self, pdf_bytes: bytes) -> bool:
        """Lightweight check if any parsed page appears image-only.

        Delegates to PdfExtractor internally.
        """
        from .extractors.pdf_extractor import PdfExtractor as _PdfExtractor

        extractor = _PdfExtractor()
        return extractor.contains_scanned_pages(pdf_bytes)
