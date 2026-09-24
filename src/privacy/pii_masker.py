import re
from typing import Tuple, List
from src.domain.schemas import SanitizedInteraction

class PIIMasker:
    """
    High-performance, deterministic PII Masker.
    Sanitizes sensitive data (Credit Cards, SSN, Emails, Phones, IBAN/Account numbers)
    BEFORE any interaction reaches the LLM or analytics store.
    """
    
    # Regex patterns for common financial PII
    PATTERNS = [
        # Credit Card: 13-19 digits, possibly separated by spaces or dashes
        (r'\b(?:\d[ -]*?){13,19}\b', "[REDACTED_CARD_NUMBER]"),
        # Email address
        (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b', "[REDACTED_EMAIL]"),
        # US/International Phone numbers
        (r'(\+?\d{1,3}[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b', "[REDACTED_PHONE]"),
        # Social Security Number (SSN)
        (r'\b\d{3}-\d{2}-\d{4}\b', "[REDACTED_SSN]"),
        # Bank Account / IBAN style patterns
        (r'\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}([A-Z0-9]?){0,16}\b', "[REDACTED_IBAN]"),
    ]

    @classmethod
    def sanitize(cls, text: str, original_id: str = "") -> SanitizedInteraction:
        sanitized = text
        detected_types: List[str] = []
        total_redactions = 0

        for pattern, replacement in cls.PATTERNS:
            matches = list(re.finditer(pattern, sanitized))
            if matches:
                entity_name = replacement.strip("[]")
                detected_types.append(entity_name)
                total_redactions += len(matches)
                sanitized = re.sub(pattern, replacement, sanitized)

        return SanitizedInteraction(
            original_id=original_id,
            sanitized_text=sanitized,
            detected_pii_types=detected_types,
            redaction_count=total_redactions
        )
