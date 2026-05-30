"""ZIP document extraction with recursive dispatch and result merging.

Opens ZIP files, iterates entries, determines type of each entry via
ExtractorRegistry, calls the appropriate extractor, and merges all
results into a single ExtractionResult using a best-confidence strategy.
"""

from io import BytesIO
from typing import Optional
from zipfile import ZipFile, BadZipFile

from ..extractor import ExtractionResult
from .base import BaseExtractor
from . import ExtractorRegistry


# ---------------------------------------------------------------------------
# Result merging helpers
# ---------------------------------------------------------------------------

_SINGULAR_FIELDS = [
    "tender_number",
    "title",
    "closing_date",
    "closing_time",
    "publication_date",
    "validity_period",
    "contract_period",
    "issuing_organization",
    "department",
    "delivery_location",
    "submission_address",
    "estimated_value",
    "bid_bond_required",
    "payment_terms",
    "document_type",
    "province",
    "contract_type",
    "procurement_threshold",
]

_LIST_FIELDS = [
    "requirements",
    "returnable_documents",
]

_TEXT_FIELDS = [
    "description",
    "full_text",
]

_OBJECT_FIELDS = [
    "bbbee",
    "contact",
    "briefing_session",
    "evaluation_criteria",
    "evaluation_structured",
    "special_conditions",
    "raw_text_preview",
]

_NON_DOCUMENT_EXTENSIONS = frozenset({
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".svg", ".ico",
    # Metadata / manifest
    ".xml", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".properties",
    # Archives (avoid infinite recursion on nested zip without clear doc content)
    ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    # Executables / binaries
    ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
    # Fonts
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # Other non-document
    ".lnk", ".url", ".lock", ".gitkeep", ".ds_store",
    ".msg",  # Outlook message (not a doc format)
})


def _first_non_none(results: list[ExtractionResult], field: str) -> object:
    """Return the first non-None value for a field across results."""
    for r in results:
        val = getattr(r, field, None)
        if val is not None:
            return val
    return None


def _dedupe_concat(lists: list[list[str]]) -> list[str]:
    """Concatenate lists, preserving order, removing duplicates."""
    seen: set[str] = set()
    result: list[str] = []
    for lst in lists:
        for item in lst:
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                result.append(item)
    return result


def merge_extraction_results(results: list[ExtractionResult]) -> ExtractionResult:
    """Merge multiple ExtractionResult objects into one.

    Strategy:
        - Singular fields: take value from result with highest confidence.
        - List fields: deduplicate and concatenate.
        - Text fields: join with ``\\n\\n---\\n\\n`` separators.
        - Object fields: take from highest-confidence result.
        - Confidence: weighted average across all results.
    """
    if not results:
        return ExtractionResult(confidence=0.0)

    if len(results) == 1:
        return results[0]

    # Find the result with highest confidence for singular/object field selection
    best = max(results, key=lambda r: r.confidence)

    merged = ExtractionResult()

    # Singular fields — copy from best
    for field in _SINGULAR_FIELDS:
        val = getattr(best, field, None)
        if val is not None:
            setattr(merged, field, val)
        else:
            # Fall back to first non-None across all results
            fallback = _first_non_none(results, field)
            if fallback is not None:
                setattr(merged, field, fallback)

    # List fields — deduplicate and concatenate
    for field in _LIST_FIELDS:
        all_lists = [getattr(r, field, []) or [] for r in results]
        setattr(merged, field, _dedupe_concat(all_lists))

    # Text fields — join with separators
    for field in _TEXT_FIELDS:
        parts = [getattr(r, field, "") or "" for r in results if getattr(r, field, "")]
        setattr(merged, field, "\n\n---\n\n".join(parts))

    # Object fields — take from highest confidence result
    for field in _OBJECT_FIELDS:
        val = getattr(best, field, None)
        if val is not None:
            setattr(merged, field, val)
        else:
            fallback = _first_non_none(results, field)
            if fallback is not None:
                setattr(merged, field, fallback)

    # Confidence: weighted average
    total_confidence = sum(r.confidence for r in results)
    merged.confidence = round(total_confidence / len(results), 2)

    # Pages used: union of all pages
    all_pages: list[int] = []
    seen_pages: set[int] = set()
    for r in results:
        for p in (r.pages_used or []):
            if p not in seen_pages:
                seen_pages.add(p)
                all_pages.append(p)
    merged.pages_used = all_pages

    # Scanned pages: True if any result detected scanned pages
    merged.scanned_pages_detected = any(r.scanned_pages_detected for r in results)

    return merged


# ---------------------------------------------------------------------------
# Entry / skip logic
# ---------------------------------------------------------------------------

def _should_skip_entry(filename: str) -> bool:
    """Return True if the entry should be skipped (non-document)."""
    idx = filename.rfind(".")
    if idx < 0:
        return True  # no extension — skip
    ext = filename[idx:].lower()
    return ext in _NON_DOCUMENT_EXTENSIONS


# ---------------------------------------------------------------------------
# ZipExtractor
# ---------------------------------------------------------------------------

class ZipExtractor(BaseExtractor):
    """Extractor for ZIP archives containing multiple tender documents.

    Opens the ZIP file, iterates entries, determines each entry's type via
    ExtractorRegistry, calls the appropriate extractor, and merges all results.
    """

    def extract(self, data: bytes, filename: Optional[str] = None) -> ExtractionResult:
        """Extract content from a ZIP archive.

        Args:
            data: Raw ZIP file bytes.
            filename: Optional original filename.

        Returns:
            Merged ExtractionResult from all document entries in the ZIP.
            If the ZIP is empty or contains only non-document entries, returns
            an empty ExtractionResult with confidence 0.
        """
        try:
            zip_file = ZipFile(BytesIO(data))
        except BadZipFile:
            return ExtractionResult(
                full_text="",
                confidence=0.0,
                requirements=["Invalid or corrupted ZIP file"],
            )

        results: list[ExtractionResult] = []

        with zip_file as zf:
            for entry_name in zf.namelist():
                # Skip directories
                if entry_name.endswith("/"):
                    continue

                # Skip non-document entries
                if _should_skip_entry(entry_name):
                    continue

                try:
                    entry_bytes = zf.read(entry_name)
                except Exception:
                    # Skip entries that cannot be read (corrupted, encrypted, etc.)
                    continue

                if not entry_bytes:
                    continue

                # Determine extractor type and extract
                extractor = ExtractorRegistry.get_extractor(
                    entry_bytes, filename=entry_name
                )

                if extractor is None:
                    # Unknown entry type — skip silently
                    continue

                try:
                    result = extractor.extract(entry_bytes, filename=entry_name)
                    results.append(result)
                except Exception:
                    # Skip entries whose extraction fails
                    continue

        return merge_extraction_results(results)
