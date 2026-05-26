"""Enhanced PDF extraction for South African tender documents.

Deterministic, fast, SA-specific.

Responsibilities:
- Extract searchable PDF text using PyMuPDF.
- Extract common South African tender fields using regex + document heuristics.
- Always return full_text where possible so the main application can run AI fallback/enrichment.
- Detect scanned/image-only pages, but do not perform OCR here.
- Keep LLM/AI logic out of this microservice.

The main application should decide when to run AI fallback based on:
- low confidence
- missing title / organization / description / requirements
- presence of full_text
- tender priority / user demand / AI cost pressure
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF


class UnsearchablePDF(Exception):
    """Raised when a PDF has too little searchable text."""
    pass


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

    # These are useful internally. They are not returned by main.py unless you
    # also update schemas.py and main.py to expose them.
    preferential_procurement: Optional[str] = None
    preference_points_system: Optional[str] = None


@dataclass
class ExtractionResult:
    """Comprehensive tender extraction result."""

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

    confidence: float = 0.0
    pages_used: list[int] = field(default_factory=list)
    raw_text_preview: Optional[str] = None
    full_text: str = ""

    # Internal signal. This is not currently exposed by schemas.py/main.py.
    scanned_pages_detected: bool = False

    @property
    def needs_ai_fallback(self) -> bool:
        """True if deterministic extraction is weak enough to justify AI fallback."""

        generic_requirements = (
            not self.requirements
            or self.requirements == ["No specific requirements found"]
            or self.requirements == ["Insufficient searchable text - AI extraction recommended"]
        )

        return (
            self.confidence < 0.55
            or not self.tender_number
            or not self.closing_date
            or not self.title
            or not self.issuing_organization
            or len(self.description or "") < 50
            or generic_requirements
        )


class TenderExtractor:
    """Extractor for South African tender PDFs with SA procurement heuristics."""

    MAX_PAGES: int = 30
    MIN_CHAR_COUNT: int = 200
    FULL_TEXT_LIMIT: int = 50000

    # -------------------------------------------------------------------------
    # Normalization patterns
    # -------------------------------------------------------------------------

    FOOTER_PATTERN = re.compile(
        r"(?:\d+\s+of\s+\d+|page\s+\d+|^\s*\d{1,3}\s*$)",
        re.MULTILINE | re.IGNORECASE,
    )

    HYPHEN_BREAK_PATTERN = re.compile(r"(\w+)-\n(\w+)")
    WHITESPACE_NORM = re.compile(r"[ \t]+")
    NEWLINE_NORM = re.compile(r"\n{3,}")

    # -------------------------------------------------------------------------
    # Section header patterns
    # -------------------------------------------------------------------------

    DESC_PATTERNS = re.compile(
        r"^\s*(?:\d+\.?\s*)?"
        r"(?:description|scope\s+of\s+(?:work|works|services?|supply|deliverables?)|"
        r"project\s+(?:overview|description|summary|background)|"
        r"background|introduction|purpose|brief\s+description|"
        r"nature\s+of\s+(?:work|works|services?|contract)|"
        r"terms?\s+of\s+reference|tor|specifications?|"
        r"c3\s+scope\s+of\s+work|scope\s+of\s+works)\s*:?\s*$",
        re.MULTILINE | re.IGNORECASE,
    )

    REQ_PATTERNS = re.compile(
        r"^\s*(?:\d+\.?\s*)?"
        r"(?:requirements?|eligibility|responsiveness|compulsory|"
        r"pre-?qualification|qualification|minimum|mandatory|"
        r"specific\s+requirements?|technical\s+requirements?|"
        r"bidder\s+requirements?|conditions?\s+(?:of|for)|"
        r"compliance|certificates?|returnable\s+documents?|"
        r"documentary\s+(?:proof|evidence))\s*:?\s*$",
        re.MULTILINE | re.IGNORECASE,
    )

    BBBEE_PATTERNS = re.compile(
        r"^\s*(?:\d+\.?\s*)?"
        r"(?:b-?bbee|bbbee|broad[- ]?based\s+black|preferential|"
        r"bee\s+(?:level|requirements?)|empowerment|transformation|"
        r"local\s+content|specific\s+goals?|preference\s+points?)\s*:?\s*$",
        re.MULTILINE | re.IGNORECASE,
    )

    EVAL_PATTERNS = re.compile(
        r"^\s*(?:\d+\.?\s*)?"
        r"(?:evaluation|adjudication|assessment|scoring|functionality|"
        r"selection|award|evaluation\s+criteria|evaluation\s+of\s+tender\s+offers?|"
        r"80\/20|90\/10|preferential\s+procurement)\s*:?\s*$",
        re.MULTILINE | re.IGNORECASE,
    )

    RETURN_PATTERNS = re.compile(
        r"^\s*(?:\d+\.?\s*)?"
        r"(?:returnable|returnable\s+documents?|documents?\s+to\s+be\s+submitted|"
        r"submission\s+checklist|required\s+documents?|checklist|"
        r"the\s+following\s+(?:documents?|forms?)\s+(?:shall|must|should)\s+be\s+"
        r"(?:submitted|attached))\s*:?\s*$",
        re.MULTILINE | re.IGNORECASE,
    )

    SPECIAL_PATTERNS = re.compile(
        r"^\s*(?:\d+\.?\s*)?"
        r"(?:special|specific|particular|additional|"
        r"contract\s+(?:terms?|conditions?))\s+conditions?\s*:?\s*$",
        re.MULTILINE | re.IGNORECASE,
    )

    CONTACT_PATTERNS = re.compile(
        r"^\s*(?:\d+\.?\s*)?"
        r"(?:contact|enquir(?:y|ies)|for\s+(?:more\s+)?information|"
        r"queries?|technical\s+(?:enquiries?|contact)|bidding\s+procedure\s+enquiries?)\s*:?\s*$",
        re.MULTILINE | re.IGNORECASE,
    )

    BRIEFING_PATTERNS = re.compile(
        r"^\s*(?:\d+\.?\s*)?"
        r"(?:(?:compulsory\s+)?briefing|site\s+(?:visit|inspection)|"
        r"pre-?(?:bid|tender)\s+(?:meeting|conference))\s*:?\s*$",
        re.MULTILINE | re.IGNORECASE,
    )

    END_PATTERNS = re.compile(
        r"^\s*(?:\d+\.?\s*)?"
        r"(?:closing|submission|page\s+\d+|annexure|appendix|attachment|"
        r"schedule|pricing|bill\s+of|form\s+of|declaration|signature|"
        r"part\s+[tc]\d+|bid\s+\d+|contract\s+data|pricing\s+data|"
        r"agreement\s+and\s+contract\s+data|the\s+contract)\s*:?\s*$",
        re.MULTILINE | re.IGNORECASE,
    )

    # -------------------------------------------------------------------------
    # Field extraction patterns
    # -------------------------------------------------------------------------

    ORG_HEADER_PATTERN = re.compile(
        r"^\s*([A-Z][A-Z\s.'’&()/,-]{3,}?"
        r"(?:MUNICIPALITY|DEPARTMENT|ENTITY|BOARD|AGENCY|COLLEGE|UNIVERSITY|"
        r"HOSPITAL|WATER|ESKOM|TRANSNET|SANRAL|AUTHORITY|COMMISSION|COUNCIL|"
        r"DISTRICT|METRO|METROPOLITAN))\s*$",
        re.MULTILINE,
    )

    TENDER_NUMBER_LINE_PATTERN = re.compile(
        r"(?:tender|bid|contract|rfq|rfp|reference)\s*"
        r"(?:number|no\.?|#)?\s*[:;]?\s*([^\n]{3,180})",
        re.IGNORECASE,
    )

    TENDER_NUMBER_ALT_PATTERN = re.compile(
        r"\b([A-Z0-9]{1,10}[/-]\d{1,6}\s*[-–—]?\s*"
        r"(?:T|RFQ|RFP|BID|SCM|COR|REQ)[A-Z0-9/.\-–—]+)\b",
        re.IGNORECASE,
    )

    CLOSING_DATE_PATTERN = re.compile(
        r"(?:closing|submission|due)\s*(?:date|time)?\s*[:;]?\s*"
        r"(\d{1,2}[\s\-/\.]*(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
        r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
        r"dec(?:ember)?)[\s\-/\.]*\d{2,4}|"
        r"\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})",
        re.IGNORECASE,
    )

    DATE_ANYWHERE_PATTERN = re.compile(
        r"\b(\d{1,2}\s*(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
        r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
        r"dec(?:ember)?)\s*\d{4})\b",
        re.IGNORECASE,
    )

    CLOSING_TIME_PATTERN = re.compile(
        r"(?:closing|submission)\s*time\s*[:;]?\s*"
        r"(\d{1,2}[:.]?\d{0,2}\s*(?:am|pm|h\d{0,2})?)",
        re.IGNORECASE,
    )

    TIME_ANYWHERE_PATTERN = re.compile(
        r"\b(\d{1,2}(?::\d{2}|h\d{0,2})\s*(?:am|pm)?)\b",
        re.IGNORECASE,
    )

    PUBLICATION_DATE_PATTERN = re.compile(
        r"(?:date\s+of\s+(?:issue|publication)|published\s+on|publication\s+date)"
        r"\s*[:;]?\s*"
        r"(\d{1,2}\s*(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
        r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
        r"dec(?:ember)?)\s*\d{4}|\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})",
        re.IGNORECASE,
    )

    EMAIL_PATTERN = re.compile(r"\b([\w.+-]+@[\w.-]+\.[a-zA-Z]{2,})\b")

    PHONE_PATTERN = re.compile(
        r"(?:tel|telephone|phone|cell|fax)?\.?\s*[:;]?\s*"
        r"(\+?27\s*[-.]?\s*\(?\d{2,3}\)?\s*[-.]?\s*\d{3}\s*[-.]?\s*\d{4}|"
        r"0\d{2}[-.\s]?\d{3}[-.\s]?\d{4})",
        re.IGNORECASE,
    )

    BBBEE_LEVEL_PATTERN = re.compile(
        r"(?:b-?bbee|bbbee|bee)?\s*(?:status\s*)?(?:level|contributor)"
        r"\s*[:;]?\s*(\d+|one|two|three|four|five)",
        re.IGNORECASE,
    )

    SPECIFIC_GOALS_PATTERN = re.compile(
        r"(?:specific\s+goals?|preference\s+points?).{0,140}?(\d{1,2})\s*points?",
        re.IGNORECASE | re.DOTALL,
    )

    PREFERENTIAL_PROC_PATTERN = re.compile(
        r"\b(80\/20|90\/10)\s*(?:preference\s+point\s+system|preferential|pppfa|ppi)?",
        re.IGNORECASE,
    )

    VALIDITY_PATTERN = re.compile(
        r"(?:validity|valid\s+for|tenders?\s+shall\s+be\s+valid\s+for)"
        r"\s*[:;]?\s*(?:a\s+period\s+of\s+)?(\d+\s*(?:days?|weeks?|months?))",
        re.IGNORECASE,
    )

    CONTRACT_PERIOD_PATTERN = re.compile(
        r"(?:contract\s+period|contract\s+duration|duration|period)"
        r"\s*[:;]?\s*(\d+\s*(?:months?|years?)|\d+\s*to\s*\d+\s*(?:months?|years?))",
        re.IGNORECASE,
    )

    VALUE_PATTERN = re.compile(
        r"(?:estimated|budget|contract)\s*(?:value|amount|cost)"
        r"\s*[:;]?\s*(R\s*[\d\s,.]+(?:\s*(?:million|mil|billion|thousand))?)",
        re.IGNORECASE,
    )

    CIDB_PATTERN = re.compile(
        r"\b(?:CIDB|CIBD)\s*(?:CATEGORY|GRADING|GRADE)?\s*[:;]?\s*"
        r"([0-9]{1,2}\s*[A-Z]{1,2}\s*(?:or\s+higher)?)",
        re.IGNORECASE,
    )

    FUNCTIONALITY_THRESHOLD_PATTERN = re.compile(
        r"(?:minimum\s+(?:qualifying\s+)?score\s+of|"
        r"minimum\s+number\s+of\s+evaluation\s+points|"
        r"minimum\s+functionality\s+score|"
        r"minimum\s+threshold\s+of)\s*(\d{1,3}\s*%?|\d{1,3}\s+points?)",
        re.IGNORECASE,
    )

    BULLET_PATTERN = re.compile(
        r"(?:^|\n)\s*(?:[-•*◦▪►➤✓→·○●]|\d+[.)]\s|[a-zA-Z][.)]\s)\s*"
    )

    RETURNABLE_HINTS = [
        "tax clearance",
        "tax compliance",
        "tcs pin",
        "csd",
        "central supplier",
        "company registration",
        "certified copies of id",
        "identity document",
        "vat registration",
        "workmen",
        "compensation",
        "coida",
        "joint venture agreement",
        "cidb",
        "cibd",
        "proof of experience",
        "completion certificate",
        "appointment letter",
        "key personnel",
        "cv",
        "qualification",
        "proof of plant",
        "logbook",
        "lease",
        "power of attorney",
        "form of intent",
        "performance guarantee",
        "mbd 1",
        "mbd 2",
        "mbd 3",
        "mbd 4",
        "mbd 5",
        "mbd 6.1",
        "mbd 7",
        "mbd 7.1",
        "mbd 7.2",
        "mbd 8",
        "mbd 9",
        "sbd 1",
        "sbd 4",
        "sbd 6.1",
        "sbd 8",
        "sbd 9",
        "wkc",
        "form of offer",
        "pricing schedule",
        "bill of quantities",
        "schedule of rates",
        "declaration of interest",
        "declaration of bidder",
        "certificate of independent bid determination",
    ]

    REQUIREMENT_PATTERNS = [
        r"(?:CIDB|CIBD)\s*(?:CATEGORY|GRADING|GRADE)?\s*[:;]?\s*[0-9]{1,2}\s*[A-Z]{1,2}\s*(?:or\s+higher)?",
        r"contractor\s+grading[^.\n;]*?[0-9]{1,2}\s*[A-Z]{1,2}\s*(?:or\s+higher)?",
        r"minimum\s+(?:qualifying\s+)?score\s+of\s+\d{1,3}\s*%?",
        r"valid\s+tax\s+clearance[^.\n;]*",
        r"tax\s+compliance[^.\n;]*",
        r"\bTCS\s+PIN[^.\n;]*",
        r"\bCSD\s+(?:number|report|registration)[^.\n;]*",
        r"central\s+supplier\s+database[^.\n;]*",
        r"company\s*/\s*cc\s*/\s*trust\s*/\s*partnership\s+registration\s+certificates?",
        r"certified\s+copies\s+of\s+id\s+certificate[^.\n;]*",
        r"vat\s+registration\s+certificate[^.\n;]*",
        r"workmen.?s\s+compensation\s+registration\s+certificate[^.\n;]*",
        r"joint\s+venture\s+agreement[^.\n;]*",
        r"power\s+of\s+attorney[^.\n;]*",
        r"valid\s+contractors?\s+(?:CIDB|CIBD)\s+registration\s+certificate[^.\n;]*",
        r"proof\s+of\s+experience[^.\n;]*",
        r"completion\s+certificate[^.\n;]*",
        r"appointment\s+letter[^.\n;]*",
        r"key\s+personnel\s+CVs?[^.\n;]*",
        r"proof\s+of\s+plant[^.\n;]*",
        r"proof\s+of\s+ownership[^.\n;]*",
        r"original\s+signed\s+letter\s+of\s+intent[^.\n;]*",
    ]

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def extract(self, pdf_bytes: bytes) -> ExtractionResult:
        """Extract tender information from PDF bytes."""

        doc = None

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text, pages_used, scanned_pages_detected = self._extract_text_optimized(doc)

            raw_text = text or ""

            if len(raw_text.strip()) < self.MIN_CHAR_COUNT:
                return ExtractionResult(
                    full_text=raw_text[: self.FULL_TEXT_LIMIT],
                    raw_text_preview=raw_text[:500] if raw_text else None,
                    pages_used=pages_used,
                    confidence=0.0,
                    requirements=["Insufficient searchable text - AI extraction recommended"],
                    scanned_pages_detected=scanned_pages_detected,
                )

            normalized_text = self._normalize_text_fast(raw_text)
            result = self._extract_all_fields(normalized_text, pages_used)

            result.scanned_pages_detected = scanned_pages_detected
            result.confidence = self._calculate_confidence(result)
            result.raw_text_preview = normalized_text[:500] if normalized_text else None
            result.full_text = normalized_text[: self.FULL_TEXT_LIMIT] if normalized_text else ""

            return result

        finally:
            if doc:
                doc.close()

    def contains_scanned_pages(self, pdf_bytes: bytes) -> bool:
        """Lightweight check if any parsed page appears image-only."""

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        try:
            for i in range(min(len(doc), self.MAX_PAGES)):
                page = doc[i]
                text = page.get_text("text")
                if not text.strip() and len(page.get_images()) > 0:
                    return True

            return False

        finally:
            doc.close()

    # -------------------------------------------------------------------------
    # Text extraction / normalization
    # -------------------------------------------------------------------------

    def _extract_text_optimized(self, doc: fitz.Document) -> tuple[str, list[int], bool]:
        """Return extracted text, pages used, and whether scanned pages were detected."""

        texts: list[str] = []
        pages_used: list[int] = []
        scanned_pages_detected = False

        page_limit = min(len(doc), self.MAX_PAGES)

        for i in range(page_limit):
            page = doc[i]
            text = page.get_text("text", sort=True)

            if text and text.strip():
                texts.append(text)
                pages_used.append(i)
            elif len(page.get_images()) > 0:
                scanned_pages_detected = True

        return "\n\n".join(texts), pages_used, scanned_pages_detected

    def _normalize_text_fast(self, text: str) -> str:
        """Normalize text while preserving useful line breaks."""

        if not text:
            return ""

        text = unicodedata.normalize("NFKC", text)
        text = text.translate(str.maketrans("", "", "\u00AD\u200B\u200C\u200D\uFEFF"))
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Join words split by line-break hyphenation, e.g. "procure-\nment".
        text = self.HYPHEN_BREAK_PATTERN.sub(r"\1\2", text)

        text = self.FOOTER_PATTERN.sub("", text)
        text = self.WHITESPACE_NORM.sub(" ", text)
        text = self.NEWLINE_NORM.sub("\n\n", text)

        return text.strip()

    # -------------------------------------------------------------------------
    # Main extraction flow
    # -------------------------------------------------------------------------

    def _extract_all_fields(self, text: str, pages_used: list[int]) -> ExtractionResult:
        """Extract all fields from normalized text."""

        result = ExtractionResult(pages_used=pages_used)

        sections = self._extract_all_sections(text)
        values = self._extract_all_values(text)

        result.description = (
            self._section_as_text(sections.get("description"))
            or self._extract_description_fallback(text)
            or ""
        )

        requirements = self._section_as_list(sections.get("requirements"))
        if not requirements:
            requirements = self._extract_requirements_fallback(text)
        result.requirements = requirements or ["No specific requirements found"]

        result.evaluation_criteria = (
            self._section_as_text(sections.get("evaluation"))
            or self._extract_evaluation_fallback(text)
            or ""
        )

        result.special_conditions = self._section_as_text(sections.get("special")) or ""

        returnables = self._section_as_list(sections.get("returnable"))
        if not returnables:
            returnables = self._extract_returnable_documents_fallback(text)
        result.returnable_documents = returnables

        result.tender_number = values.get("tender_number")
        result.title = values.get("title")
        result.closing_date = values.get("closing_date")
        result.closing_time = values.get("closing_time")
        result.publication_date = values.get("publication_date")
        result.validity_period = values.get("validity")
        result.contract_period = values.get("contract_period")
        result.issuing_organization = values.get("organization")
        result.department = values.get("department")
        result.delivery_location = values.get("delivery_location")
        result.submission_address = values.get("submission_address")
        result.estimated_value = values.get("value")

        result.bbbee = self._extract_bbbee_fast(
            text,
            self._section_as_text(sections.get("bbbee_section")),
        )
        result.contact = self._extract_contact_fast(
            text,
            self._section_as_text(sections.get("contact_section")),
        )
        result.briefing_session = self._extract_briefing_fast(
            text,
            self._section_as_text(sections.get("briefing_section")),
        )

        result.bid_bond_required = self._extract_bid_bond(text)
        result.payment_terms = self._extract_payment_terms(text)

        return result

    # -------------------------------------------------------------------------
    # Section extraction
    # -------------------------------------------------------------------------

    def _extract_all_sections(self, text: str) -> dict[str, str | list[str]]:
        """Extract and merge named sections using header positions."""

        patterns = {
            "description": self.DESC_PATTERNS,
            "requirements": self.REQ_PATTERNS,
            "bbbee": self.BBBEE_PATTERNS,
            "evaluation": self.EVAL_PATTERNS,
            "returnable": self.RETURN_PATTERNS,
            "special": self.SPECIAL_PATTERNS,
            "contact": self.CONTACT_PATTERNS,
            "briefing": self.BRIEFING_PATTERNS,
        }

        matches: list[tuple[int, int, str]] = []

        for name, pattern in patterns.items():
            for match in pattern.finditer(text):
                matches.append((match.start(), match.end(), name))

        matches.sort()

        if not matches:
            return {}

        merged: dict[str, str] = {name: "" for name in patterns.keys()}

        for i, (_start, end, name) in enumerate(matches):
            next_start = matches[i + 1][0] if i + 1 < len(matches) else len(text)

            end_match = self.END_PATTERNS.search(text, end)
            if end_match and end_match.start() < next_start:
                next_start = end_match.start()

            section_text = text[end:next_start].strip()

            if not section_text:
                continue

            if merged.get(name):
                merged[name] += "\n\n" + section_text
            else:
                merged[name] = section_text

        result: dict[str, str | list[str]] = {}

        for name, section_text in merged.items():
            if not section_text:
                continue

            if name in ("bbbee", "contact", "briefing"):
                result[f"{name}_section"] = section_text
            elif name in ("requirements", "returnable"):
                result[name] = self._parse_list_fast(section_text)
            else:
                result[name] = section_text

        return result

    def _parse_list_fast(self, text: str) -> list[str]:
        """Parse bullet/numbered lists."""

        if not text:
            return []

        items = self.BULLET_PATTERN.split(text)

        cleaned: list[str] = []

        for item in items:
            clean = self._clean_line(item)

            if len(clean) > 10 and clean not in cleaned:
                cleaned.append(clean)

        return cleaned[:30]

    # -------------------------------------------------------------------------
    # Scalar value extraction
    # -------------------------------------------------------------------------

    def _extract_all_values(self, text: str) -> dict[str, Optional[str]]:
        """Extract scalar values."""

        values: dict[str, Optional[str]] = {}

        values["tender_number"] = self._extract_tender_number(text)
        values["title"] = self._extract_title(text)
        values["organization"] = self._extract_organization(text)

        publication = self.PUBLICATION_DATE_PATTERN.search(text[:5000])
        values["publication_date"] = self._clean_line(publication.group(1)) if publication else None

        closing_context = self._window_around(
            text,
            ["closing date", "closing time", "submission deadline", "closing"],
            900,
        )

        date_source = closing_context if closing_context else text[:5000]
        date_match = self.CLOSING_DATE_PATTERN.search(date_source)
        if date_match:
            values["closing_date"] = self._clean_line(date_match.group(1))
        else:
            fallback_date = self.DATE_ANYWHERE_PATTERN.search(date_source)
            values["closing_date"] = self._clean_line(fallback_date.group(1)) if fallback_date else None

        time_match = self.CLOSING_TIME_PATTERN.search(date_source)
        if time_match:
            values["closing_time"] = self._clean_line(time_match.group(1))
        else:
            fallback_time = self.TIME_ANYWHERE_PATTERN.search(date_source)
            values["closing_time"] = self._clean_line(fallback_time.group(1)) if fallback_time else None

        validity = self.VALIDITY_PATTERN.search(text)
        values["validity"] = self._clean_line(validity.group(1)) if validity else None

        contract_period = self.CONTRACT_PERIOD_PATTERN.search(text)
        values["contract_period"] = self._clean_line(contract_period.group(1)) if contract_period else None

        value = self.VALUE_PATTERN.search(text)
        values["value"] = self._clean_line(value.group(1)) if value else None

        values["department"] = self._extract_department(text)
        values["delivery_location"] = self._extract_delivery_location(text)
        values["submission_address"] = self._extract_submission_address(text)

        return values

    def _extract_tender_number(self, text: str) -> Optional[str]:
        """Extract full tender/reference number without truncating after slashes."""

        for match in self.TENDER_NUMBER_LINE_PATTERN.finditer(text[:7000]):
            candidate = self._clean_line(match.group(1))
            candidate = self._trim_after_keywords(
                candidate,
                [
                    "closing date",
                    "closing time",
                    "description",
                    "cidb",
                    "cibd",
                    "name of tenderer",
                    "name of bidder",
                    "telephone",
                    "fax",
                    "address",
                ],
            )

            if self._looks_like_reference(candidate):
                return candidate

        match = self.TENDER_NUMBER_ALT_PATTERN.search(text[:7000])
        if match:
            return self._clean_line(match.group(1))

        return None

    def _extract_title(self, text: str) -> Optional[str]:
        """Extract tender title using explicit patterns, then first-page heuristics."""

        title_patterns = [
            r"(?:description)\s*:?\s*(.+?)(?:\n|$)",
            r"(?:tender|bid)\s+(?:for|:)\s+(.+?)(?:\n|$)",
            r"(?:project\s+(?:name|title))\s*:?\s*(.+?)(?:\n|$)",
        ]

        for pattern in title_patterns:
            match = re.search(pattern, text[:5000], re.IGNORECASE)
            if match:
                title = self._clean_line(match.group(1))
                if self._looks_like_title(title):
                    return title[:300]

        lines = self._first_lines(text, limit=35)
        candidates: list[str] = []

        for line in lines:
            lower = line.lower()

            if len(line) < 18:
                continue

            if "municipality" in lower and len(line) < 100:
                continue

            if any(
                skip in lower
                for skip in [
                    "tender number",
                    "contract document",
                    "name of tenderer",
                    "telephone number",
                    "fax number",
                    "tender sum",
                    "closing date",
                    "prepared by",
                    "table of contents",
                    "contents",
                    "part t1",
                    "part t2",
                    "part c1",
                    "part c2",
                ]
            ):
                continue

            if lower in {
                "the bid",
                "bid procedures",
                "invitation to tender",
                "part a",
                "part b",
                "terms and conditions for bidding",
            }:
                continue

            if any(
                keyword in lower
                for keyword in [
                    "hire",
                    "supply",
                    "delivery",
                    "services",
                    "maintenance",
                    "construction",
                    "appointment",
                    "provision",
                    "repairs",
                    "upgrade",
                    "infrastructure",
                    "security",
                    "cleaning",
                    "roads",
                    "software",
                    "hardware",
                    "consulting",
                    "professional",
                    "panel",
                ]
            ):
                candidates.append(line)

        if candidates:
            title = " ".join(candidates[:2])
            return self._clean_line(title)[:300]

        return None

    def _extract_organization(self, text: str) -> Optional[str]:
        """Extract issuing organization."""

        match = self.ORG_HEADER_PATTERN.search(text[:4000])
        if match:
            return self._title_case_organization(match.group(1))

        org_patterns = [
            r"(?:issued\s+by|employer)\s*:?\s*(.+?)(?:\n|$)",
            r"(?:name\s+of\s+municipality/municipal\s+entity)\s*:?\s*(.+?)(?:\n|$)",
            r"(?:department\s+of)\s+(.+?)(?:\n|$)",
            r"requirements\s+of\s+the\s+(.+?)(?:\n|$)",
        ]

        for pattern in org_patterns:
            match = re.search(pattern, text[:6000], re.IGNORECASE | re.MULTILINE)
            if match:
                org = self._clean_line(match.group(1))

                if 5 < len(org) < 200:
                    return org

        return None

    def _extract_department(self, text: str) -> Optional[str]:
        """Extract department/unit where visible."""

        patterns = [
            r"\bdepartment\s*:?\s*(.+?)(?:\n|$)",
            r"\bunit\s*:?\s*(.+?)(?:\n|$)",
            r"\bpmu\s+unit\b",
            r"\bsupply\s+chain\s+management\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, text[:8000], re.IGNORECASE)

            if match:
                value = self._clean_line(match.group(1) if match.groups() else match.group(0))

                if 3 < len(value) < 120:
                    return value

        return None

    def _extract_delivery_location(self, text: str) -> Optional[str]:
        """Extract delivery/work location."""

        patterns = [
            r"(?:delivery\s+(?:location|address)|place\s+of\s+delivery)\s*:?\s*(.+?)(?:\n|$)",
            r"((?:in\s+)?ward\s+\d+)",
            r"((?:Nongoma|Durban|Pretoria|Johannesburg|Cape Town|Polokwane|Bloemfontein|Kimberley|Mbombela|Mahikeng)[^.\n]{0,120})",
        ]

        for pattern in patterns:
            match = re.search(pattern, text[:10000], re.IGNORECASE)

            if match:
                value = self._clean_line(match.group(1))

                if 3 < len(value) < 200:
                    return value

        return None

    def _extract_submission_address(self, text: str) -> Optional[str]:
        """Extract bid-box / submission address."""

        context = self._window_around(
            text,
            ["tender box", "bid box", "deposited", "submission address", "delivered to"],
            900,
        )

        if not context:
            return None

        address_patterns = [
            r"((?:Lot|No\.?|Number)?\s*\d+[^.\n]{0,180}(?:Street|Road|Avenue|Drive|Offices?|Building|Nongoma|Durban|Pretoria|Cape Town)[^.\n]*)",
            r"(Tender Box[^.\n]{0,220})",
            r"(Bid Box[^.\n]{0,220})",
        ]

        for pattern in address_patterns:
            match = re.search(pattern, context, re.IGNORECASE)

            if match:
                value = self._clean_line(match.group(1))

                if 5 < len(value) < 260:
                    return value

        return self._clean_line(context[:250])

    # -------------------------------------------------------------------------
    # Fallback extractors
    # -------------------------------------------------------------------------

    def _extract_description_fallback(self, text: str) -> str:
        """Extract a useful scope/description when formal section parsing fails."""

        patterns = [
            r"DESCRIPTION\s+(.+?)(?:\n[A-Z][A-Z\s]{5,}|THE SUCCESSFUL BIDDER|BID RESPONSE)",
            r"Bidders\s+are\s+hereby\s+invited\s+to\s+tender\s+their\s+proposal\s+for\s+(.+?)(?:There will be|Bid documents|All technical)",
            r"((?:Plant\s+Hire|Supply|Provision|Appointment|Construction|Maintenance|Repairs|Upgrade).{20,500}?(?:services?|works?|goods?|project|maintenance))",
            r"((?:Supply|Provision|Appointment|Construction|Maintenance|Repairs|Upgrade).{20,350})",
        ]

        for pattern in patterns:
            match = re.search(pattern, text[:10000], re.IGNORECASE | re.DOTALL)

            if match:
                value = self._clean_paragraph(match.group(1))

                if len(value) > 20:
                    return value[:1200]

        title = self._extract_title(text)
        return title or ""

    def _extract_requirements_fallback(self, text: str) -> list[str]:
        """Extract practical supplier requirements when formal sections fail."""

        requirements: list[str] = []

        cidb = self.CIDB_PATTERN.search(text)
        if cidb:
            requirements.append(f"CIDB grading/category: {self._clean_line(cidb.group(1))}")

        threshold = self.FUNCTIONALITY_THRESHOLD_PATTERN.search(text)
        if threshold:
            requirements.append(
                f"Minimum functionality/qualifying score: {self._clean_line(threshold.group(1))}"
            )

        for pattern in self.REQUIREMENT_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                item = self._clean_line(match.group(0))

                if item and len(item) > 8 and item not in requirements:
                    requirements.append(item)

        relevant_context = self._join_windows(
            text,
            [
                "certificates must be provided",
                "eligibility",
                "responsiveness",
                "documentary proof",
                "disqualifying factors",
                "returnable documents",
                "functionality score",
                "minimum qualifying score",
                "bidder must",
                "bidders must",
                "must be attached",
                "must be submitted",
            ],
            window=1500,
        )

        for line in relevant_context.splitlines():
            clean = self._clean_line(line)
            lower = clean.lower()

            if len(clean) < 12:
                continue

            if any(hint in lower for hint in self.RETURNABLE_HINTS):
                if clean not in requirements:
                    requirements.append(clean)

        return self._dedupe_keep_order(requirements)[:30]

    def _extract_returnable_documents_fallback(self, text: str) -> list[str]:
        """Extract returnable document/checklist items."""

        returnables: list[str] = []

        context = self._join_windows(
            text,
            [
                "certificates must be provided",
                "returnable documents",
                "documents must be submitted",
                "must be attached",
                "documentary proof",
                "documents as listed",
                "verification documents",
            ],
            window=1800,
        )

        for line in context.splitlines():
            clean = self._clean_line(line)
            lower = clean.lower()

            if len(clean) < 12:
                continue

            if any(hint in lower for hint in self.RETURNABLE_HINTS):
                returnables.append(clean)

        return self._dedupe_keep_order(returnables)[:30]

    def _extract_evaluation_fallback(self, text: str) -> str:
        """Extract evaluation criteria/functionality information."""

        context = self._join_windows(
            text,
            [
                "evaluation",
                "functionality",
                "80/20",
                "90/10",
                "preferential procurement",
                "quality",
                "specific goals",
                "minimum qualifying score",
                "stage 1",
                "stage 2",
            ],
            window=2200,
        )

        if not context:
            return ""

        useful_lines: list[str] = []

        for line in context.splitlines():
            clean = self._clean_line(line)
            lower = clean.lower()

            if len(clean) < 10:
                continue

            if any(
                keyword in lower
                for keyword in [
                    "functionality",
                    "80/20",
                    "90/10",
                    "70",
                    "specific goals",
                    "quality",
                    "preference",
                    "evaluation",
                    "score",
                    "points",
                    "stage",
                    "financial offer",
                    "pppfa",
                ]
            ):
                useful_lines.append(clean)

        return "\n".join(self._dedupe_keep_order(useful_lines)[:25])

    # -------------------------------------------------------------------------
    # Complex object extraction
    # -------------------------------------------------------------------------

    def _extract_bbbee_fast(self, text: str, section: str) -> Optional[BBBEEInfo]:
        """Extract B-BBEE, specific goals, and preference point system."""

        search_text = section if section else text

        level_match = self.BBBEE_LEVEL_PATTERN.search(search_text)
        specific_goals_match = self.SPECIFIC_GOALS_PATTERN.search(search_text)
        preference_system_match = self.PREFERENTIAL_PROC_PATTERN.search(search_text)

        bbbee_context = self._window_around(
            text,
            [
                "b-bbee",
                "bbbee",
                "specific goals",
                "preference points",
                "historical disadvantaged",
                "black person owned",
                "80/20",
                "90/10",
                "pppfa",
            ],
            1800,
        )

        if not level_match and not specific_goals_match and not preference_system_match and not bbbee_context:
            return None

        bbbee = BBBEEInfo()

        if level_match:
            bbbee.minimum_level = self._clean_line(level_match.group(1))

        if specific_goals_match:
            bbbee.points_allocation = f"{self._clean_line(specific_goals_match.group(1))} points"

        if preference_system_match:
            bbbee.preferential_procurement = self._clean_line(preference_system_match.group(1))

        if section:
            bbbee.details = self._clean_paragraph(section[:1800])
        elif bbbee_context:
            bbbee.details = self._clean_paragraph(bbbee_context[:1800])

        if bbbee.preferential_procurement and bbbee.points_allocation:
            bbbee.preference_points_system = (
                f"{bbbee.preferential_procurement} preference system; "
                f"{bbbee.points_allocation} specific-goals/preference points detected"
            )
        elif bbbee.preferential_procurement:
            bbbee.preference_points_system = f"{bbbee.preferential_procurement} preference system"

        return bbbee if (
            bbbee.minimum_level
            or bbbee.points_allocation
            or bbbee.details
            or bbbee.preferential_procurement
        ) else None

    def _extract_contact_fast(self, text: str, section: str) -> Optional[ContactInfo]:
        """Extract contact details."""

        search_text = section if section else text[:10000]

        contact = ContactInfo()

        email_match = self.EMAIL_PATTERN.search(search_text)
        if email_match:
            contact.email = email_match.group(1)

        phone_match = self.PHONE_PATTERN.search(search_text)
        if phone_match:
            contact.phone = self._clean_line(phone_match.group(1))

        name_patterns = [
            r"(?:contact\s+person|technical\s+information\s+may\s+be\s+directed\s+to|contact)\s*:?\s*"
            r"((?:Mr|Ms|Mrs|Dr)\.?\s+[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})",
            r"\b((?:Mr|Ms|Mrs|Dr)\.?\s+[A-Z]\.?\s*[A-Z][A-Za-z.'-]+)\b",
            r"Contact\s+Person\s*:\s*([^\n]{3,80})",
        ]

        for pattern in name_patterns:
            match = re.search(pattern, search_text, re.IGNORECASE)

            if match:
                name = self._clean_line(match.group(1))
                if 3 < len(name) < 100:
                    contact.name = name
                    break

        department_patterns = [
            r"(?:department|unit)\s*:?\s*(.+?)(?:\n|$)",
            r"\b(Supply\s+Chain\s+Management)\b",
            r"\b(PMU\s+Unit)\b",
        ]

        for pattern in department_patterns:
            match = re.search(pattern, search_text, re.IGNORECASE)
            if match:
                department = self._clean_line(match.group(1))
                if 3 < len(department) < 100:
                    contact.department = department
                    break

        address_context = self._window_around(search_text, ["address", "lot", "street"], 400)
        if address_context:
            address_line = self._clean_line(address_context.splitlines()[0])
            if 5 < len(address_line) < 180:
                contact.address = address_line

        return contact if (
            contact.email or contact.phone or contact.name or contact.department or contact.address
        ) else None

    def _extract_briefing_fast(self, text: str, section: str) -> Optional[BriefingSession]:
        """Extract briefing/site inspection details."""

        if re.search(
            r"there\s+will\s+be\s+no\s+(?:tender\s+)?briefing|"
            r"no\s+(?:compulsory\s+)?(?:briefing|site\s+inspection|site\s+visit)",
            text,
            re.IGNORECASE,
        ):
            return BriefingSession(is_compulsory=False)

        search_text = section

        if not search_text:
            match = re.search(
                r"(?:compulsory\s+)?(?:briefing|site\s+(?:visit|inspection)).{0,900}",
                text,
                re.IGNORECASE | re.DOTALL,
            )

            if not match:
                return None

            search_text = match.group(0)

        briefing = BriefingSession()
        briefing.is_compulsory = bool(re.search(r"compulsory|mandatory", search_text, re.IGNORECASE))

        date_match = self.DATE_ANYWHERE_PATTERN.search(search_text)
        if date_match:
            briefing.date = self._clean_line(date_match.group(1))

        time_match = self.TIME_ANYWHERE_PATTERN.search(search_text)
        if time_match:
            briefing.time = self._clean_line(time_match.group(1))

        venue_match = re.search(r"(?:venue|at)\s*:?\s*(.+?)(?:\n|$)", search_text, re.IGNORECASE)
        if venue_match:
            venue = self._clean_line(venue_match.group(1))

            if 3 < len(venue) < 200:
                briefing.venue = venue

        return briefing if (
            briefing.date or briefing.time or briefing.venue or briefing.is_compulsory
        ) else None

    def _extract_bid_bond(self, text: str) -> Optional[str]:
        """Extract bid-bond/performance-guarantee requirement."""

        match = re.search(
            r"(?:bid\s+bond|bid\s+guarantee|performance\s+guarantee|form\s+of\s+guarantee).{0,300}",
            text,
            re.IGNORECASE | re.DOTALL,
        )

        return self._clean_paragraph(match.group(0)) if match else None

    def _extract_payment_terms(self, text: str) -> Optional[str]:
        """Extract payment terms if available."""

        match = re.search(
            r"(?:payment\s+terms|certificate\s+of\s+payment|payment\s+certificate).{0,350}",
            text,
            re.IGNORECASE | re.DOTALL,
        )

        return self._clean_paragraph(match.group(0)) if match else None

    # -------------------------------------------------------------------------
    # Confidence
    # -------------------------------------------------------------------------

    def _calculate_confidence(self, result: ExtractionResult) -> float:
        """Calculate confidence score from extracted fields."""

        score = 0.0

        if result.title:
            score += 1.2
        if result.issuing_organization:
            score += 1.0
        if len(result.description or "") > 50:
            score += 1.3
        if result.requirements and result.requirements[0] != "No specific requirements found":
            score += 1.8
        if result.tender_number:
            score += 1.0
        if result.closing_date:
            score += 1.0
        if result.closing_time:
            score += 0.5
        if result.contact:
            score += 0.6
        if result.evaluation_criteria:
            score += 0.8
        if result.returnable_documents:
            score += 0.7
        if result.bbbee:
            score += 0.5
        if result.submission_address:
            score += 0.3
        if result.scanned_pages_detected:
            score -= 0.2

        return round(max(0.0, min(1.0, score / 9.7)), 2)

    # -------------------------------------------------------------------------
    # Utility helpers
    # -------------------------------------------------------------------------

    def _section_as_text(self, value: object) -> str:
        if isinstance(value, str):
            return value.strip()

        if isinstance(value, list):
            return "\n".join(str(item) for item in value if item).strip()

        return ""

    def _section_as_list(self, value: object) -> list[str]:
        if isinstance(value, list):
            return [
                self._clean_line(str(item))
                for item in value
                if self._clean_line(str(item))
            ]

        if isinstance(value, str) and value.strip():
            return self._parse_list_fast(value)

        return []

    def _clean_line(self, value: str) -> str:
        value = value or ""
        value = re.sub(r"\s+", " ", value)
        return value.strip(" :-–—\t\n\r")

    def _clean_paragraph(self, value: str) -> str:
        value = value or ""
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n{2,}", "\n", value)
        return value.strip(" :-–—\t\n\r")

    def _first_lines(self, text: str, limit: int = 20) -> list[str]:
        lines: list[str] = []

        for raw_line in text.splitlines():
            clean = self._clean_line(raw_line)

            if clean:
                lines.append(clean)

            if len(lines) >= limit:
                break

        return lines

    def _looks_like_title(self, value: str) -> bool:
        lower = value.lower()

        if len(value) < 10 or len(value) > 300:
            return False

        if any(
            term in lower
            for term in [
                "closing date",
                "closing time",
                "name of bidder",
                "name of tenderer",
                "signature",
                "telephone number",
                "fax number",
                "address",
            ]
        ):
            return False

        return True

    def _looks_like_reference(self, value: str) -> bool:
        if len(value) < 3 or len(value) > 120:
            return False

        has_digit = bool(re.search(r"\d", value))
        has_reference_mark = bool(re.search(r"[A-Za-z/-]", value))

        return has_digit and has_reference_mark

    def _trim_after_keywords(self, value: str, keywords: list[str]) -> str:
        result = value

        for keyword in keywords:
            idx = result.lower().find(keyword.lower())

            if idx > 0:
                result = result[:idx]

        return self._clean_line(result)

    def _window_around(self, text: str, keywords: list[str], window: int = 600) -> str:
        lower = text.lower()

        for keyword in keywords:
            idx = lower.find(keyword.lower())

            if idx >= 0:
                start = max(0, idx - window // 3)
                end = min(len(text), idx + window)
                return text[start:end]

        return ""

    def _join_windows(self, text: str, keywords: list[str], window: int = 1000) -> str:
        chunks: list[str] = []
        lower = text.lower()

        for keyword in keywords:
            idx = lower.find(keyword.lower())

            if idx >= 0:
                start = max(0, idx - window // 4)
                end = min(len(text), idx + window)
                chunk = text[start:end]

                if chunk not in chunks:
                    chunks.append(chunk)

        return "\n\n".join(chunks)

    def _dedupe_keep_order(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []

        for value in values:
            clean = self._clean_line(value)
            key = clean.lower()

            if not clean or key in seen:
                continue

            seen.add(key)
            result.append(clean)

        return result

    def _title_case_organization(self, value: str) -> str:
        clean = self._clean_line(value)

        known_upper = {
            "ESKOM",
            "TRANSNET",
            "SANRAL",
            "PRASA",
            "SARS",
            "SAPS",
            "SITA",
            "CIDB",
            "CIPC",
            "DBSA",
        }

        if clean.upper() in known_upper:
            return clean.upper()

        return clean.title()