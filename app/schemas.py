"""Pydantic schemas for tender extraction API request/response models."""

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional


class ExtractRequest(BaseModel):
    """Request model for URL-based PDF extraction."""
    
    url: Optional[HttpUrl] = Field(
        default=None,
        description="URL of the tender PDF document to extract"
    )


class ContactInfo(BaseModel):
    """Extracted contact information."""
    
    name: Optional[str] = Field(default=None, description="Contact person name")
    email: Optional[str] = Field(default=None, description="Email address")
    phone: Optional[str] = Field(default=None, description="Phone number")
    department: Optional[str] = Field(default=None, description="Department or unit name")
    address: Optional[str] = Field(default=None, description="Physical address")


class BriefingSession(BaseModel):
    """Briefing session or site visit details."""
    
    date: Optional[str] = Field(default=None, description="Date of briefing session")
    time: Optional[str] = Field(default=None, description="Time of briefing session")
    venue: Optional[str] = Field(default=None, description="Location/venue")
    is_compulsory: bool = Field(default=False, description="Whether attendance is compulsory")


class BBBEEInfo(BaseModel):
    """B-BBEE (Broad-Based Black Economic Empowerment) requirements."""
    
    minimum_level: Optional[str] = Field(default=None, description="Minimum B-BBEE level required")
    points_allocation: Optional[str] = Field(default=None, description="Points allocated for B-BBEE")
    details: Optional[str] = Field(default=None, description="Full B-BBEE requirements text")
    local_content_requirement: Optional[str] = Field(default=None, description="Local content minimum percentage requirement")
    hdi_requirement: Optional[str] = Field(default=None, description="HDI sub-contracting obligation")


class EvaluationSubCriterion(BaseModel):
    """A single evaluation sub-criterion with its point weight."""

    criterion: str = Field(..., description="Name of the evaluation criterion")
    weight: int = Field(..., description="Point weight assigned to this criterion")


class EvaluationCriteria(BaseModel):
    """Structured evaluation criteria with system type and sub-criteria."""

    system: Optional[str] = Field(default=None, description="Preference point system (80/20 or 90/10)")
    functionality_threshold: Optional[str] = Field(default=None, description="Minimum functionality/qualifying score")
    sub_criteria: list[EvaluationSubCriterion] = Field(default_factory=list, description="Named sub-criteria with point weights")
    details: Optional[str] = Field(default=None, description="Full evaluation criteria text")


class ExtractResponse(BaseModel):
    """Response model for tender extraction results with comprehensive fields."""
    
    # Core fields
    description: str = Field(
        ...,
        description="Cleaned plain-text description/scope of work"
    )
    requirements: list[str] = Field(
        ...,
        description="List of requirements extracted from the tender"
    )
    
    # Tender identification
    tender_number: Optional[str] = Field(
        default=None,
        description="Tender/bid reference number"
    )
    title: Optional[str] = Field(
        default=None,
        description="Tender title or name"
    )
    
    # Dates
    closing_date: Optional[str] = Field(
        default=None,
        description="Submission deadline date"
    )
    closing_time: Optional[str] = Field(
        default=None,
        description="Submission deadline time"
    )
    publication_date: Optional[str] = Field(
        default=None,
        description="Date tender was published"
    )
    validity_period: Optional[str] = Field(
        default=None,
        description="How long the bid must remain valid"
    )
    contract_period: Optional[str] = Field(
        default=None,
        description="Duration of the contract"
    )
    
    # Organization
    issuing_organization: Optional[str] = Field(
        default=None,
        description="Organization issuing the tender"
    )
    department: Optional[str] = Field(
        default=None,
        description="Department within organization"
    )
    
    # Location
    delivery_location: Optional[str] = Field(
        default=None,
        description="Where goods/services must be delivered"
    )
    submission_address: Optional[str] = Field(
        default=None,
        description="Physical address for bid submission"
    )
    
    # Financial
    estimated_value: Optional[str] = Field(
        default=None,
        description="Estimated contract value if disclosed"
    )
    bid_bond_required: Optional[str] = Field(
        default=None,
        description="Bid guarantee/bond requirements"
    )
    payment_terms: Optional[str] = Field(
        default=None,
        description="Payment terms or conditions"
    )
    
    # B-BBEE
    bbbee: Optional[BBBEEInfo] = Field(
        default=None,
        description="B-BBEE requirements and scoring"
    )
    
    # Contact & Sessions
    contact: Optional[ContactInfo] = Field(
        default=None,
        description="Contact person details"
    )
    briefing_session: Optional[BriefingSession] = Field(
        default=None,
        description="Briefing session or site visit details"
    )
    
    # Additional extracted sections
    evaluation_criteria: Optional[str] = Field(
        default=None,
        description="How bids will be evaluated/scored"
    )
    special_conditions: Optional[str] = Field(
        default=None,
        description="Special conditions of contract"
    )
    returnable_documents: list[str] = Field(
        default_factory=list,
        description="List of documents to be submitted with bid"
    )
    
    # NEW: Phase 1 extraction enhancements
    document_type: str = Field(
        default="unknown",
        description="Document type classification: RFQ, TENDER, EOI, RFP, or unknown"
    )
    province: Optional[str] = Field(
        default=None,
        description="Province extracted from document text"
    )
    contract_type: Optional[str] = Field(
        default=None,
        description="Contract framework type: NEC3, JBCC, GCC2010, GCC2015, FIDIC, etc."
    )
    procurement_threshold: Optional[str] = Field(
        default=None,
        description="Procurement threshold classification label"
    )
    evaluation_structured: Optional[EvaluationCriteria] = Field(
        default=None,
        description="Structured evaluation criteria with sub-criteria and weightings"
    )
    
    # Metadata
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Extraction confidence score (0.0-1.0)"
    )
    pages_used: list[int] = Field(
        ...,
        description="0-indexed page numbers that were analyzed"
    )
    raw_text_preview: Optional[str] = Field(
        default=None,
        description="First 500 chars of extracted text for debugging"
    )
    full_text: Optional[str] = Field(
        default=None,
        description="Complete extracted text (up to 50KB) for AI fallback when regex fails"
    )


class HealthResponse(BaseModel):
    """Response model for health check endpoint."""
    
    status: str = Field(default="healthy")
    version: str = Field(...)
