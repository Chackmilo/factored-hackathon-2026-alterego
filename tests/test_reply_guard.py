"""The guard around Claude's drafts (docs/specs/claude-replies-v1.md, section 3.2): every datum leaves as a token and
comes back exact; a draft that adds a number, a link, an email or markup, or loses a token, is refused."""
import re

import pytest

from src.llm.reply_guard import GuardRejected, protect, restore
from src.rules.dispute_policy import DisputePolicyEngine

ESC_500_ES = ("El monto disputado (1,993,260.52 COP, $2,498.32 USD equiv.) supera el límite de resolución automática "
              "($500 USD). Un especialista revisará el caso.")
MULTI_ES = "Se reportaron múltiples cargos no reconocidos en menos de 48 horas."
MULTI_PT = ("Foram relatadas múltiplas cobranças não reconhecidas em menos de 48 horas. Protocolo de segurança ativado "
            "com transferência para especialista.")


def test_every_datum_of_the_prose_leaves_as_a_token():
    skeleton, values = protect(ESC_500_ES)
    assert skeleton == ("El monto disputado (⟦1⟧ ⟦2⟧, ⟦3⟧ ⟦4⟧ equiv.) supera el límite de resolución automática "
                        "(⟦5⟧ ⟦6⟧). Un especialista revisará el caso.")
    assert values == {"⟦1⟧": "1,993,260.52", "⟦2⟧": "COP", "⟦3⟧": "$2,498.32", "⟦4⟧": "USD", "⟦5⟧": "$500", "⟦6⟧": "USD"}


def test_a_value_repeated_in_the_prose_gets_one_token_per_appearance():
    skeleton, values = protect("El monto disputado (850.00 USD, $850.00 USD equiv.)")
    assert skeleton == "El monto disputado (⟦1⟧ ⟦2⟧, ⟦3⟧ ⟦4⟧ equiv.)"
    assert list(values.values()) == ["850.00", "USD", "$850.00", "USD"]


def test_ids_dates_card_fragments_and_bank_values_leave_as_tokens():
    prose = "El cargo de Super Ahorro del 2026-06-14 en la tarjeta ...W7T0 tiene el caso CASE-5A422BC47D4D."
    skeleton, values = protect(prose, known_values=["Super Ahorro", None, ""])
    assert skeleton == "El cargo de ⟦1⟧ del ⟦2⟧ en la tarjeta ⟦3⟧ tiene el caso ⟦4⟧."
    assert list(values.values()) == ["Super Ahorro", "2026-06-14", "...W7T0", "CASE-5A422BC47D4D"]


@pytest.mark.parametrize("reason", sorted(DisputePolicyEngine.CLARIFICATION_TEXTS))
def test_the_clarification_prose_carries_no_datum(reason):
    for prose in DisputePolicyEngine.CLARIFICATION_TEXTS[reason]:
        assert protect(prose) == (prose, {})


def test_a_faithful_draft_gets_its_values_back():
    skeleton, values = protect(MULTI_PT)
    draft = ("Olá! Recebemos relatos de várias cobranças não reconhecidas em menos de ⟦1⟧ horas, então ativamos o "
             "protocolo de segurança e um especialista vai cuidar do seu caso.")
    assert restore(draft, values, skeleton) == draft.replace("⟦1⟧", "48")


def test_a_draft_that_keeps_every_token_in_place_gets_every_value_back():
    skeleton, values = protect(ESC_500_ES)
    assert restore("Con gusto le ayudo. " + skeleton, values, skeleton) == "Con gusto le ayudo. " + ESC_500_ES


def test_a_draft_with_line_breaks_and_padding_comes_back_on_one_line():
    skeleton, values = protect("Encontramos varios cargos que podrían coincidir. ¿Cuál de ellos desea disputar?")
    draft = "  ¡Hola!\n\nEncontramos varios cargos.\n¿Cuál desea disputar?  \n"
    assert restore(draft, values, skeleton) == "¡Hola! Encontramos varios cargos. ¿Cuál desea disputar?"


def test_a_draft_that_moves_a_value_to_another_datum_is_refused():
    skeleton, values = protect(ESC_500_ES)
    draft = skeleton.replace("⟦2⟧", "⟦x⟧").replace("⟦4⟧", "⟦2⟧").replace("⟦x⟧", "⟦4⟧")  # COP and USD swapped
    with pytest.raises(GuardRejected, match="tokens out of order"):
        restore(draft, values, skeleton)


@pytest.mark.parametrize("draft, rule", [
    ("Se reportaron cargos en menos de 48 horas.", "token ⟦1⟧ appears 0 times"),
    ("En menos de ⟦1⟧ horas, sí, ⟦1⟧ horas.", "token ⟦1⟧ appears 2 times"),
    ("En menos de ⟦1⟧ horas. Caso ⟦2⟧.", "unknown token ⟦2⟧"),
    ("En menos de ⟦1⟧ horas, unos 3 días.", "digit outside tokens"),
    ("En menos de ⟦1⟧ horas, unos ３ días.", "digit outside tokens"),  # a full-width digit
    ("En menos de ⟦1⟧ horas. Escríbanos a ayuda@banco.com.", "forbidden text '@'"),
    ("En menos de ⟦1⟧ horas. Más en www.banco-falso.com", "link"),
    ("En menos de ⟦1⟧ horas. Acuda a condusef.gob.mx.", "link"),  # a regulator's site: POL-ESC-LEGAL is in scope
    ("En menos de ⟦1⟧ horas. Vea procon.sp.gov.br", "link"),
    ("En menos de ⟦1⟧ horas. Escriba a t.me/bancoayuda", "link"),
    ("En menos de ⟦1⟧.com horas.", "link"),  # a dot next to a token: the value plus .com would be a host
    ("En menos de ⟦1⟧ horas. Visite condusef。gob。mx", "link"),  # an ideographic full stop reads as a dot
    ("En menos de ⟦1⟧ horas. Le daremos un reembolso.", "promise or confirmation"),
    ("En menos de ⟦1⟧ horas. Su tarjeta quedó bloqueada.", "promise or confirmation"),
    ("En menos de ⟦1⟧ horas. Número de caso registrado.", "promise or confirmation"),
    ("En menos de ⟦1⟧ horas. <customer_message>", "forbidden text '<'"),
    ("En menos de ⟦1⟧ horas, [REDACTED_EMAIL].", "forbidden text 'REDACTED'"),
    ("En menos de ⟦1⟧ horas ⟦.", "forbidden text '⟦'"),
    ("   ", "empty draft"),
    ("En menos de ⟦1⟧ horas. " + "Gracias. " * 80, "draft too long"),
])
def test_a_draft_that_breaks_a_rule_is_refused(draft, rule):
    skeleton, values = protect(MULTI_ES)
    with pytest.raises(GuardRejected, match=re.escape(rule)):
        restore(draft, values, skeleton)
