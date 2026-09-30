import re

from src.domain.schemas import SanitizedInteraction


class PIIMasker:
    """
    High-performance, deterministic PII Masker.
    Sanitizes sensitive data (Credit Cards, SSN, Emails, Phones, IBAN/Account numbers)
    BEFORE any interaction reaches the LLM or analytics store.
    """

    # Regex patterns for financial and identity PII, applied in order. Documents run before phones so a
    # labeled id is never read as a phone, and phones need a country code, parentheses or separators so a
    # 7-digit COP or ARS amount is never masked (SEC-05). Amount and date hints are extracted from the raw
    # text before masking (src/understand), so a masked digit run never costs the policy an amount.
    PATTERNS = [
        # Credit or debit card: 13 to 19 digits, possibly separated by spaces or dashes
        (r'\b(?:\d[ -]*?){13,19}\b', "[REDACTED_CARD_NUMBER]"),
        # Email address
        (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b', "[REDACTED_EMAIL]"),
        # LATAM identity documents: CURP (Mexico), CPF (Brazil), labeled DNI, cedula or CC, Argentine DNI with dots
        (r'\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b', "[REDACTED_DOCUMENT]"),
        (r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b', "[REDACTED_DOCUMENT]"),
        (r'(?i)\b(?:dni|c[eé]dula|cc|c\.c\.|documento|cpf|curp|rfc)\s*(?:n[°º]?\.?|:)?\s*[\d.\-]{6,14}\b', "[REDACTED_DOCUMENT]"),
        (r'\b\d{2}\.\d{3}\.\d{3}\b', "[REDACTED_DOCUMENT]"),
        # Phones: international prefix, parentheses, or separators between groups
        (r'\+\d{1,3}[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}\b', "[REDACTED_PHONE]"),
        (r'\(\d{2,3}\)\s?\d{3,4}[\s-]\d{4}\b', "[REDACTED_PHONE]"),
        (r'\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b', "[REDACTED_PHONE]"),
        # Social Security Number (SSN)
        (r'\b\d{3}-\d{2}-\d{4}\b', "[REDACTED_SSN]"),
        # Bank Account / IBAN style patterns
        (r'\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}([A-Z0-9]?){0,16}\b', "[REDACTED_IBAN]"),
    ]

    @classmethod
    def sanitize(cls, text: str, original_id: str = "") -> SanitizedInteraction:
        sanitized = text
        detected_types: list[str] = []
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
