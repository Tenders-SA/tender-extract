# Tender Extract API Reference

Base URL: `http://localhost:8000` (Local) / Configured Service URL (Production)

## Overview

The Tender Extract API is a FastAPI-based microservice designed to extract structured data from South African government tender PDF documents. It primarily uses deterministic regex-based pattern matching to identify key sections and fields.

## Endpoints

### 1. Health Check

**GET** `/health`

Checks the operational status of the service.

**Response** (`200 OK`)

```json
{
  "status": "healthy",
  "version": "0.1.0"
}
```

---

### 2. Extract Tender Data

**POST** `/v1/extract`

Extracts comprehensive information from a provided PDF file or a URL pointing to a PDF.

#### Request

The endpoint supports two modes of operation:

**Mode A: File Upload (Multipart)**

- **Content-Type**: `multipart/form-data`
- **Body**:
    - `file`: The PDF file to be processed.

**Mode B: URL Fetch (JSON)**

- **Content-Type**: `application/json`
- **Body**:

```json
{
  "url": "https://example.gov.za/path/to/tender.pdf"
}
```

#### Response (`200 OK`)

Returns a JSON object matching the `ExtractResponse` model.

**Example Structure:**

```json
{
  "description": "Supply and delivery of...",
  "requirements": ["Requirement 1...", "Requirement 2..."],
  "tender_number": "ABC-123",
  "title": "Tender Title",
  "closing_date": "2024-01-31",
  "closing_time": "11:00",
  "issuing_organization": "Department of Public Works",
  "estimated_value": "R 500,000.00",
  "bbbee": {
    "minimum_level": "1",
    "points_allocation": "80/20"
  },
  "contact": {
    "name": "John Doe",
    "email": "john@example.gov.za",
    "phone": "012 345 6789"
  },
  "confidence": 0.95,
  "pages_used": [0, 1]
}
```

### Models

#### ExtractResponse Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| **Core** | | |
| `description` | `string` | Cleaned plain-text description/scope of work. |
| `requirements` | `list[str]` | List of requirements extracted from the tender. |
| **Identification** | | |
| `tender_number` | `string` | Tender/bid reference number. |
| `title` | `string` | Tender title or name. |
| **Dates** | | |
| `closing_date` | `string` | Submission deadline date. |
| `closing_time` | `string` | Submission deadline time. |
| `publication_date` | `string` | Date tender was published. |
| `validity_period` | `string` | How long the bid must remain valid. |
| `contract_period` | `string` | Duration of the contract. |
| **Organization** | | |
| `issuing_organization` | `string` | Organization issuing the tender. |
| `department` | `string` | Department within the organization. |
| **Location** | | |
| `delivery_location` | `string` | Where goods/services must be delivered. |
| `submission_address` | `string` | Physical address for bid submission. |
| **Financial** | | |
| `estimated_value` | `string` | Estimated contract value if disclosed. |
| `bid_bond_required` | `string` | Bid guarantee/bond requirements. |
| `payment_terms` | `string` | Payment terms or conditions. |
| **B-BBEE** | | |
| `bbbee` | `BBBEEInfo` | B-BBEE requirements and scoring. |
| **Contact** | | |
| `contact` | `ContactInfo` | Contact person details. |
| `briefing_session` | `BriefingSession`| Briefing session or site visit details. |
| **Other** | | |
| `evaluation_criteria` | `string` | How bids will be evaluated/scored. |
| `special_conditions` | `string` | Special conditions of contract. |
| `returnable_documents`| `list[str]` | List of documents to be submitted. |
| `confidence` | `float` | Extraction confidence score (0.0-1.0). |
| `pages_used` | `list[int]` | 0-indexed page numbers analyzed. |

#### Nested Objects

**BBBEEInfo**
- `minimum_level`: `string`
- `points_allocation`: `string`
- `details`: `string`

**ContactInfo**
- `name`: `string`
- `email`: `string`
- `phone`: `string`
- `department`: `string`
- `address`: `string`

**BriefingSession**
- `date`: `string`
- `time`: `string`
- `venue`: `string`
- `is_compulsory`: `boolean`

## Error Codes

| Code | Description |
| :--- | :--- |
| `415` | **Unsupported Media Type**: Uploaded file is not a PDF. |
| `422` | **Unprocessable Entity**: File/Request invalid (e.g., file too large, fetch failure). |
| `501` | **Not Implemented**: Scanned PDF detected (extraction not supported). |
| `504` | **Gateway Timeout**: URL fetch timed out. |
| `500` | **Internal Server Error**: Unexpected extraction failure. |
