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


# ------------------------------------------------------------ SEC-05: LATAM documents, amounts are not phones

@pytest.mark.parametrize("text", [
    "Me cobraron 2500000 pesos que no reconozco",
    "El cargo fue de $2.500.000 COP el 12 de junio",
    "Um valor de 1.250.000 ARS apareceu no extrato",
])
def test_amounts_are_not_masked_as_phones(text):
    result = PIIMasker.sanitize(text)
    assert "[REDACTED_PHONE]" not in result.sanitized_text
    assert result.redaction_count == 0


@pytest.mark.parametrize("text, expected", [
    ("Llámenme al +57 300 123 4567", "[REDACTED_PHONE]"),
    ("Mi celular es (55) 1234-5678", "[REDACTED_PHONE]"),
    ("Mi CURP es GOMC850101HDFRRL09", "[REDACTED_DOCUMENT]"),
    ("Mi DNI es 12.345.678", "[REDACTED_DOCUMENT]"),
    ("DNI 40123456 a nombre mío", "[REDACTED_DOCUMENT]"),
    ("Cédula 1.020.304.050 de Bogotá", "[REDACTED_DOCUMENT]"),
    ("mi cc 1020304050 por favor", "[REDACTED_DOCUMENT]"),
    ("Meu CPF é 123.456.789-09", "[REDACTED_DOCUMENT]"),
])
def test_latam_phones_and_documents_are_masked(text, expected):
    result = PIIMasker.sanitize(text)
    assert expected in result.sanitized_text
    assert result.redaction_count >= 1
