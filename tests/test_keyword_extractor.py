"""
The ES/PT keyword extractor: the Understand fallback, and on every turn (Jev included) the source of amounts, dates,
yes or no and option numbers. Messages are team-written.
"""
from datetime import date

import pytest

from src.understand.jev_extractor import StubJev
from src.understand.keyword_extractor import KeywordIntentExtractor
from src.understand.router import UnderstandRouter

extract = KeywordIntentExtractor().extract


@pytest.mark.parametrize("text, option", [
    ("Es la opción 3.", 3), ("sería el número 2, gracias", 2), ("Quiero la 1 por favor", 1), ("Nº 4", 4), ("Elijo el 2", 2),
    ("É a opção 3.", 3), ("seria o número 2, obrigada", 2), ("Escolho o 1", 1), ("quero a 4, por favor", 4),
    ("2", 2), ("la 1.", 1), ("  3)  ", 3), ("Número 5.", 5),
])
def test_a_reply_naming_one_listed_number_selects_it(text, option):
    assert extract(text).selected_option == option


@pytest.mark.parametrize("text", [
    "hace 3 días", "fue el 4 de junio", "o 3 de julho", "el 3/6", "$3", "3 dólares", "5 mil", "13", "la 12", "el 0",
    "el 1 y el 2", "no es el 2", "não é a 2", "ni la 1 ni la 3", "Sí", "não", "compré 3 cosas en la tienda", "la 2 no",
])
def test_a_number_that_is_a_date_an_amount_or_a_negation_selects_nothing(text):
    assert extract(text).selected_option is None


@pytest.mark.parametrize("text, intent, category", [
    ("Olhando o extrato vi uma cobrança indevida", "cobro_indebido", None),
    ("En mi estado de cuenta hay una compra que no hice", "cargo_no_reconocido", None),
    ("Necesito el extracto de abril, por favor", "fuera_de_alcance", "saldo_o_extracto"),
    ("No reconozco el cobro de la cuota del préstamo", "fuera_de_alcance", "prestamo_o_credito"),  # other products stay out of scope
    # a loose dispute word without a named charge is still a statement request
    ("¿Cuál es mi saldo? Ya pregunté dos veces", "fuera_de_alcance", "saldo_o_extracto"),
    ("Já pedi o extrato duas vezes e não chegou", "fuera_de_alcance", "saldo_o_extracto"),
    ("Desconozco cómo descargar mi extracto", "fuera_de_alcance", "saldo_o_extracto"),
    ("Necesito el extracto porque no hice el pago a tiempo", "fuera_de_alcance", "saldo_o_extracto"),
    ("Pedí el extracto dos veces y no llega, quiero revisar mis compras", "fuera_de_alcance", "saldo_o_extracto"),
    ("No hice ninguna compra este mes, ¿me envían el extracto?", "fuera_de_alcance", "saldo_o_extracto"),
    ("Desconozco cómo ver mis compras en el extracto", "fuera_de_alcance", "saldo_o_extracto"),
    ("No reconozco mi saldo", "fuera_de_alcance", "saldo_o_extracto"),
    ("No reconozco mi saldo de 80 dólares", "fuera_de_alcance", "saldo_o_extracto"),  # the amount of a balance names no charge
    ("Não reconheço meu saldo de 80 dólares", "fuera_de_alcance", "saldo_o_extracto"),
    ("Quiero el extracto de la transferencia que no hice a tiempo", "fuera_de_alcance", "saldo_o_extracto"),
    ("Quiero mi extracto: hice el pago dos veces?", "fuera_de_alcance", "saldo_o_extracto"),
    # a clause that names one charge in other words (a disputable type, a statement line, an amount) and disputes it
    ("No reconozco un pago de 80 dólares en mi estado de cuenta", "cargo_no_reconocido", None),
    ("Não reconheço um lançamento no meu extrato", "cargo_no_reconocido", None),
    ("En mi estado de cuenta aparece un retiro de 200 mil pesos que no hice", "cargo_no_reconocido", None),
    ("En el extracto veo un movimiento de 120 dólares que no reconozco", "cargo_no_reconocido", None),
    ("No reconozco los 300 dólares que salen en mi extracto", "cargo_no_reconocido", None),
])
def test_dispute_language_wins_over_a_statement_mention_only(text, intent, category):
    result = extract(text)
    assert (result.intent, result.out_of_scope_category) == (intent, category)


@pytest.mark.parametrize("text, intent, category", [
    ("Vi en el extracto un cargo de 35 dólares que no es mío", "cargo_no_reconocido", None),
    ("En mi estado de cuenta hay una compra de 20 dólares que no es mía", "cargo_no_reconocido", None),
    ("Esos dos retiros que salen en el extracto no son míos", "cargo_no_reconocido", None),
    ("tengo un cargo en el extracto de 10 dolares que no es mio", "cargo_no_reconocido", None),
    ("No es mío ese cobro del martes", "cargo_no_reconocido", None),
    ("No meu extrato tem um lançamento de 30 dólares que não é meu", "cargo_no_reconocido", None),
    ("Os saques que aparecem no extrato não são meus", "cargo_no_reconocido", None),
    # what is not mine names no charge: the statement or the balance itself
    ("El extracto que me llegó no es mío", "fuera_de_alcance", "saldo_o_extracto"),
    ("Mi saldo de 80 dólares no es mío", "fuera_de_alcance", "saldo_o_extracto"),
])
def test_a_charge_that_is_not_mine_is_disputed(text, intent, category):
    result = extract(text)
    assert (result.intent, result.out_of_scope_category) == (intent, category)


@pytest.mark.parametrize("text, amounts", [
    ("No reconozco tres cargos: uno de 45 dólares, otro de 80 dólares y otro de 120 dólares", [45.0, 80.0, 120.0]),
    ("No reconozco los cargos de 45, 80 y 120 dólares", [45.0, 80.0, 120.0]),  # a list shares the unit of its last amount
    ("Não reconheço duas compras: US$ 30 e US$ 75", [30.0, 75.0]),
    ("No reconozco un cargo de 1.250.000 pesos", [1250000.0]),
    ("No reconozco un cargo de 80 dólares del 12 de junio", [80.0]),  # a date is no amount
    ("Mi saldo es de 500 dólares y no reconozco un cargo de 80 dólares", [80.0]),  # the amount of a balance names no charge
])
def test_every_amount_a_message_names_is_read(text, amounts):
    assert extract(text).amount_hints == amounts


@pytest.mark.parametrize("text, charge_date", [
    ("Extravié mi tarjeta de débito anteayer en el bus", None),
    ("Ontem à noite perdi o cartão no metrô", None),
    ("Me robaron la tarjeta el sábado y ayer me llegó un cobro de 30 dólares", date(2026, 6, 16)),
    ("Roubaram meu cartão e ontem apareceu uma compra de 50 reais", date(2026, 6, 16)),
    ("Ayer no reconozco un cargo de 80 dólares en Oxxo", date(2026, 6, 16)),
    ("No reconozco el cargo de 50 dólares, lo aprobaron ayer sin mi permiso", date(2026, 6, 16)),  # "aprobaron" is no theft
    ("Me robaron la tarjeta y ayer la usaron en una tienda", date(2026, 6, 16)),
    ("Ayer, me robaron la tarjeta y hay un cargo que no reconozco", None),  # the comma does not take the day off the theft
    ("El 5 de junio, me robaron la tarjeta y hay un cargo que no reconozco", None),
    ("Me robaron la tarjeta. Fue ayer.", None),
    ("No reconozco una compra de 80 dólares. Fue ayer. Me robaron la tarjeta", date(2026, 6, 16)),  # a sentence of its own
    ("El 5 de junio, me robaron la tarjeta. El 12 de junio hicieron una compra de 200 dólares", date(2026, 6, 12)),
    # a date in the clause of the theft is left out: dropping it only widens the candidates, keeping it can pin a wrong charge
    ("El cobro de 85.000 pesos de ayer es un robo", None),
    ("La tarjeta que me robaron ayer la usaron en una tienda", None),
    ("Ayer me robaron la billetera con 100 dólares en efectivo", None),  # money alone tells no charge
    # an amount the customer disputes tells the charge, so its own date stays
    ("Me robaron la tarjeta, ayer aparecieron 300 dólares en Amazon que no reconozco", date(2026, 6, 16)),
    ("Me robaron la tarjeta. Ayer vi 85.000 pesos que no reconozco", date(2026, 6, 16)),
    # a sentence that only dates the theft, or that tells no charge, dates nothing
    ("Me robaron la tarjeta. Fue el 13 de junio. Hay 35 dólares que no reconozco", None),
    ("Perdí la tarjeta. Fue ayer. Hay 80 dólares que no reconozco", None),
    ("Ayer. Me robaron la tarjeta y hay un cargo que no reconozco", None),
])
def test_a_loss_date_is_not_the_charge_date(text, charge_date):
    assert extract(text).date_hint == charge_date
    with_jev, _ = UnderstandRouter(jev=StubJev()).understand(text, "new")
    assert with_jev.date_hint == charge_date  # Jev keeps the local slots, so both engines read the same date


@pytest.mark.parametrize("text, said_yes, said_no", [
    ("No reconozco un cargo de 80 dólares en Oxxo", False, False),  # the "no" of a dispute phrase answers nothing
    ("Não reconheço essa compra de 50 reais", False, False),
    ("No, no la bloqueen, las compras no las hice yo", False, True),
    ("No, gracias, solo quería revisar una compra", False, True),
    ("Não, obrigado, foram 50 reais", False, True),
    ("Sí, bloquéenla, y no reconozco un cobro de 30 dólares", False, False),  # a yes the whole message overrules is asked again
    ("No", False, True), ("Sí", True, False),
    # taking the dispute phrases out never makes a yes: the lock needs the customer's own yes
    ("Si no reconozco la compra, ¿qué pasa?", False, False),
    ("Confirmo que no hice esa compra", False, False),
    ("Quero falar com alguém, não fiz essas compras", False, False),
    # a no is a refusal when it refuses (the lock, or bare) or when no charge is told; a charge told after a plain no is asked again
    ("No lo reconozco, es un cargo de 80 dólares en Oxxo", False, False),
    ("No sé qué es ese cargo de 80 dólares", False, False),
    ("Não reconheco essas compras", False, False),  # accents typed halfway
    ("Não quero bloquear", False, True),
    ("No quiero que la bloqueen", False, True),
    ("No sé si bloquearla", False, False),
    ("No gracias", False, True),
    ("No, bloquéala", False, False),  # a refusal and a lock in one answer contradict each other: asked again
])
def test_yes_or_no_is_read_without_the_dispute_phrases(text, said_yes, said_no):
    result = extract(text)
    assert (result.said_yes, result.said_no) == (said_yes, said_no)


@pytest.mark.parametrize("text, said_yes, said_no", [
    # a lock needs a closed yes: every word says yes, nothing asks or waits
    ("Sí", True, False), ("si porfa", True, False), ("siii", True, False), ("Dale", True, False), ("ok", True, False),
    ("Claro", True, False), ("Sim", True, False), ("Pode", True, False), ("sim sim", True, False),
    ("Sí, bloquéenla por favor", True, False), ("Sim, pode bloquear", True, False), ("Bloquéenla ya", True, False),
    ("Ok, bloquéela", True, False), ("no hay problema bloquéala", True, False), ("sí, no importa bloquéala", True, False),
    ("Cómo no, bloquéenla", True, False),
    ("¿Qué pasa si la bloqueo?", False, False), ("Si la bloqueo, ¿puedo desbloquearla después?", False, False),
    ("¿Y si mejor espero a encontrarla?", False, False), ("Quero pensar um pouco antes", False, False),
    ("Podemos esperar até amanhã?", False, False), ("Sigo buscándola, un momento", False, False),
    ("Sinceramente prefiero esperar", False, False), ("ok, déjame buscarla en casa primero", False, False),
    ("Pode ser que eu tenha deixado em casa", False, False), ("No fui yo, lo confirmo", False, False),
    ("Não reconheço, pode ser fraude", False, False), ("sim?", False, False),
    ("sim perdi no onibus pode bloquear", False, False),  # "no" is "in the": not a closed yes, and no refusal either
    ("Sí, bloquéenla, no quiero que nadie la use", False, False),
    ("No importa", False, False), ("Não importa", False, False), ("No importa, gracias", False, False),  # "never mind" is no yes
    ("Sim, não quero que usem", False, False), ("No quiero que la sigan usando, sí por favor", False, False),  # a yes with its reason
    ("Dale, no quiero que la usen", False, False), ("Claro, no quiero perder la tarjeta", False, False),
    ("Sí, no gracias", False, False),  # a yes and a refusal at once contradict each other: asked again
    ("Sí ❌", False, False),  # a sign the vocabulary cannot read keeps the answer from being a closed yes
    # a refusal refuses the lock
    ("No", False, True), ("Não", False, True), ("nao obrigado", False, True), ("Mejor no", False, True), ("Ahora no", False, True),
    ("No la bloqueen", False, True), ("Não bloqueie", False, True), ("Claro que no", False, True), ("Prefiero que no", False, True),
    ("Para nada", False, True), ("Nem pensar", False, True), ("No me interesa", False, True),
    ("No quiero", False, True), ("No quiero nada", False, True), ("Não quero, obrigado", False, True),  # a want refuses on its own
    ("No quiero que me la bloqueen", False, True), ("No importa, no la bloqueen", False, True),
])
def test_a_lock_answer_locks_only_on_a_closed_yes(text, said_yes, said_no):
    result = extract(text)
    assert (result.said_yes, result.said_no) == (said_yes, said_no)


@pytest.mark.parametrize("text", [
    "¿Cuánto tiempo tengo para disputar un cargo?", "¿Cómo funciona la disputa de un cargo?", "¿Qué compras se pueden disputar?",
    "¿Me devuelven el dinero mientras revisan?", "cuanto tiempo tengo para reclamar", "¿Cómo desbloqueo mi tarjeta después?",
    "Quanto tempo tenho para contestar uma cobrança?", "Como funciona a contestação?", "Posso contestar um saque?",
    "O que acontece depois que eu contesto?",
])
def test_a_question_about_the_dispute_rules_is_a_policy_question(text):
    assert extract(text).policy_question is True


@pytest.mark.parametrize("text", [
    "¿Cuánto tiempo tengo para el cargo de 300 dólares que no reconozco?",  # an amount and a disputed charge
    "¿Cuánto tiempo tengo para disputar un cargo de 300 dólares?",  # an amount alone names one charge
    "¿Qué pasa si no fui yo?",  # a dispute phrase with no charge word
    "¿Puedo disputar el cargo de ayer?",  # a date names one charge
    "¿Puedo disputar este cargo?",  # so does a demonstrative
    "No reconozco un cargo, ¿qué pasa ahora?",
    "¿Qué pasa si me cobraron dos veces?",
    "Me robaron la tarjeta, ¿cuánto tiempo tengo?",
    "Tengo un problema con un cargo, ¿me ayudan?",  # asks for help with a charge, not about the rules
    "Necesito disputar un cargo, el plazo se me vence",  # a request, not a question
    "Buenas, tengo un cargo de 21.929,78 pesos el 10 de junio que no reconozco, ¿me ayudan?",
    "¿Cuál es el plazo de mi préstamo?",  # another product
    "Quanto tempo tenho para contestar a compra de 50 reais de ontem?",
    "Não reconheço uma cobrança, o que acontece agora?",
])
def test_a_message_about_one_charge_or_another_product_is_never_a_policy_question(text):
    assert extract(text).policy_question is False
