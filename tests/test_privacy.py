import pytest
from src.privacy.pii_masker import PIIMasker

def test_pii_masker_redacts_credit_card():
    raw = "My card number is 4532 1234 5678 9012, please help."
    result = PIIMasker.sanitize(raw)
    assert "[REDACTED_CARD_NUMBER]" in result.sanitized_text
    assert "4532 1234 5678 9012" not in result.sanitized_text
    assert result.redaction_count >= 1

def test_pii_masker_redacts_email_and_phone():
    raw = "Contact me at alice@bankdomain.com or call +1 555-839-2019."
    result = PIIMasker.sanitize(raw)
    assert "[REDACTED_EMAIL]" in result.sanitized_text
    assert "[REDACTED_PHONE]" in result.sanitized_text
    assert result.redaction_count == 2

def test_clean_text_remains_untouched():
    raw = "Hello, what is my account balance?"
    result = PIIMasker.sanitize(raw)
    assert result.sanitized_text == raw
    assert result.redaction_count == 0
