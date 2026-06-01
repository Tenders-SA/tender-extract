"""Tests for ZIP extraction result merging logic.

The merge_extraction_results() function takes a list of ExtractionResult
objects and produces a single merged result using:
  - Best-confidence selection for singular fields
  - Dedup concatenation for list fields
  - Weighted average for confidence
  - Separator-joined text for description/full_text
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.extractor import ExtractionResult
from app.extractors.zip_extractor import (
    merge_extraction_results,
    _dedupe_concat,
    _first_non_none,
)


# =========================================================================
# _dedupe_concat helper tests
# =========================================================================


class TestDedupeConcat:
    """Tests for the _dedupe_concat string deduplication helper."""

    def test_empty_lists(self):
        """Empty input list returns empty list."""
        assert _dedupe_concat([]) == []

    def test_all_empty_lists(self):
        """Lists with only empty lists produce empty result."""
        assert _dedupe_concat([[], [], []]) == []

    def test_single_list(self):
        """Single list returns its items in order."""
        items = ["tax clearance", "company registration", "CIDB grading"]
        assert _dedupe_concat([items]) == items

    def test_dedup_identical(self):
        """Identical items across lists are deduplicated (case-insensitive)."""
        result = _dedupe_concat([
            ["Tax Clearance", "Company Registration"],
            ["tax clearance", "CIDB Grading"],
        ])
        assert result == ["Tax Clearance", "Company Registration", "CIDB Grading"]

    def test_dedup_case_difference(self):
        """Case difference in items still deduplicates."""
        result = _dedupe_concat([
            ["Tax Clearance Certificate"],
            ["TAX CLEARANCE CERTIFICATE"],
        ])
        assert len(result) == 1

    def test_dedup_whitespace_difference(self):
        """Whitespace differences are normalized before dedup."""
        result = _dedupe_concat([
            ["  Tax Clearance  "],
            ["Tax Clearance"],
        ])
        assert len(result) == 1

    def test_order_preserved(self):
        """First occurrence order is preserved."""
        result = _dedupe_concat([
            ["Item A", "Item B"],
            ["Item C", "Item A", "Item D"],
        ])
        assert result == ["Item A", "Item B", "Item C", "Item D"]

    def test_empty_strings_skipped(self):
        """Empty strings are excluded from results."""
        result = _dedupe_concat([["", "valid item", ""]])
        assert result == ["valid item"]


# =========================================================================
# _first_non_none helper tests
# =========================================================================


class TestFirstNonNone:
    """Tests for the _first_non_none field value helper."""

    def test_first_non_none_returns_first(self):
        """Returns the first non-None value for a field."""
        results = [
            ExtractionResult(title=None),
            ExtractionResult(title="Second Title"),
            ExtractionResult(title="Third Title"),
        ]
        assert _first_non_none(results, "title") == "Second Title"

    def test_first_non_none_all_none(self):
        """Returns None when all field values are None."""
        results = [
            ExtractionResult(tender_number=None),
            ExtractionResult(tender_number=None),
        ]
        assert _first_non_none(results, "tender_number") is None

    def test_first_non_none_with_mixed(self):
        """Works across mixed None/valued results."""
        results = [
            ExtractionResult(closing_date=None),
            ExtractionResult(closing_date="2026-06-30"),
            ExtractionResult(closing_date=None),
        ]
        assert _first_non_none(results, "closing_date") == "2026-06-30"


# =========================================================================
# merge_extraction_results tests
# =========================================================================


class TestMergeExtractionResults:
    """Tests for the merge_extraction_results function."""

    def test_empty_list(self):
        """Empty result list returns fallback ExtractionResult."""
        result = merge_extraction_results([])
        assert isinstance(result, ExtractionResult)
        assert result.confidence == 0.0
        assert result.requirements == ["No document content found in ZIP archive"]
        assert result.full_text == ""

    def test_single_result(self):
        """Single result is returned as-is."""
        single = ExtractionResult(
            full_text="Test content",
            description="A test document",
            confidence=0.8,
            tender_number="SCM/2026/001",
        )
        result = merge_extraction_results([single])
        assert result is single  # Same object returned

    def test_single_field_from_best_confidence(self):
        """Singular fields are taken from the highest-confidence result."""
        r1 = ExtractionResult(
            title="Title from Low Confidence",
            confidence=0.3,
            full_text="First doc",
        )
        r2 = ExtractionResult(
            title="Title from High Confidence",
            confidence=0.9,
            full_text="Second doc",
        )
        result = merge_extraction_results([r1, r2])
        assert result.title == "Title from High Confidence"

    def test_requirements_dedup_concat(self):
        """Requirements lists are deduplicated and concatenated."""
        r1 = ExtractionResult(
            requirements=["Tax Clearance", "CIDB Grading"],
            confidence=0.5,
            full_text="doc1",
        )
        r2 = ExtractionResult(
            requirements=["tax clearance", "Company Registration"],
            confidence=0.5,
            full_text="doc2",
        )
        result = merge_extraction_results([r1, r2])
        assert "Tax Clearance" in result.requirements
        assert "CIDB Grading" in result.requirements
        assert "Company Registration" in result.requirements
        assert len(result.requirements) == 3  # tax clearance deduplicated

    def test_returnable_documents_dedup_concat(self):
        """Returnable documents are deduplicated and concatenated."""
        r1 = ExtractionResult(
            returnable_documents=["SBD 1", "SBD 4"],
            confidence=0.5,
            full_text="doc1",
        )
        r2 = ExtractionResult(
            returnable_documents=["SBD 4", "Tax Clearance Certificate"],
            confidence=0.5,
            full_text="doc2",
        )
        result = merge_extraction_results([r1, r2])
        assert "SBD 1" in result.returnable_documents
        assert "SBD 4" in result.returnable_documents
        assert "Tax Clearance Certificate" in result.returnable_documents
        assert len(result.returnable_documents) == 3

    def test_text_fields_joined_with_separator(self):
        """Description and full_text are joined with separator."""
        r1 = ExtractionResult(
            description="Description from doc 1",
            full_text="Full text of first document.",
            confidence=0.5,
        )
        r2 = ExtractionResult(
            description="Description from doc 2",
            full_text="Full text of second document.",
            confidence=0.5,
        )
        result = merge_extraction_results([r1, r2])
        assert "\n\n---\n\n" in result.description
        assert "\n\n---\n\n" in result.full_text
        assert "first document" in result.full_text
        assert "second document" in result.full_text

    def test_confidence_weighted_average(self):
        """Confidence is the weighted average of all results."""
        r1 = ExtractionResult(confidence=0.8, full_text="doc1")
        r2 = ExtractionResult(confidence=0.6, full_text="doc2")
        r3 = ExtractionResult(confidence=0.4, full_text="doc3")
        result = merge_extraction_results([r1, r2, r3])
        # Average: (0.8 + 0.6 + 0.4) / 3 = 0.6
        assert result.confidence == 0.6

    def test_confidence_rounds_to_two_decimals(self):
        """Confidence average is rounded to 2 decimal places."""
        r1 = ExtractionResult(confidence=0.33, full_text="doc1")
        r2 = ExtractionResult(confidence=0.33, full_text="doc2")
        r3 = ExtractionResult(confidence=0.33, full_text="doc3")
        result = merge_extraction_results([r1, r2, r3])
        assert result.confidence == 0.33

    def test_pages_used_union(self):
        """pages_used is the union of all pages across results."""
        r1 = ExtractionResult(pages_used=[0, 1, 2], confidence=0.5, full_text="doc1")
        r2 = ExtractionResult(pages_used=[2, 3, 4], confidence=0.5, full_text="doc2")
        result = merge_extraction_results([r1, r2])
        assert result.pages_used == [0, 1, 2, 3, 4]

    def test_scanned_pages_detected_union(self):
        """scanned_pages_detected is True if any result detected scanned pages."""
        r1 = ExtractionResult(scanned_pages_detected=False, confidence=0.5, full_text="doc1")
        r2 = ExtractionResult(scanned_pages_detected=True, confidence=0.5, full_text="doc2")
        result = merge_extraction_results([r1, r2])
        assert result.scanned_pages_detected is True

    def test_mixed_field_merge(self):
        """Complex merge with mixed field types."""
        r1 = ExtractionResult(
            description="Scope of work for road construction",
            full_text="Tender document for road construction in Eastern Cape.",
            tender_number="SCM/2026/001",
            closing_date="2026-06-30",
            requirements=["Tax Clearance", "CIDB Grading 7CE"],
            confidence=0.7,
            pages_used=[0, 1],
            bbbee=None,
        )
        r2 = ExtractionResult(
            description="Pricing schedule for road materials",
            full_text="Bill of quantities for road construction materials.",
            tender_number=None,
            closing_date=None,
            requirements=["tax clearance", "Company Registration"],
            confidence=0.5,
            pages_used=[0],
            bbbee=None,
        )
        result = merge_extraction_results([r1, r2])

        # Best confidence values
        assert result.tender_number == "SCM/2026/001"
        assert result.closing_date == "2026-06-30"

        # Deduped requirements
        assert "Tax Clearance" in result.requirements
        assert "CIDB Grading 7CE" in result.requirements
        assert "Company Registration" in result.requirements
        assert len(result.requirements) == 3

        # Separator-joined text
        assert "\n\n---\n\n" in result.description
        assert "road construction" in result.full_text
        assert "pricing schedule" in result.description.lower() or "scope" in result.description.lower()

        # Confidence average
        assert result.confidence == 0.6  # (0.7 + 0.5) / 2

    def test_first_non_none_fallback_for_singular(self):
        """When best has None for a field, falls back to first non-None."""
        r1 = ExtractionResult(
            tender_number=None,
            closing_date=None,
            confidence=0.9,
            full_text="Best doc",
        )
        r2 = ExtractionResult(
            tender_number="TEN/2026/002",
            closing_date="2026-07-15",
            confidence=0.4,
            full_text="Second doc",
        )
        result = merge_extraction_results([r1, r2])
        # Best is r1 (0.9), but tender_number is None -> falls back to r2
        assert result.tender_number == "TEN/2026/002"
        assert result.closing_date == "2026-07-15"
