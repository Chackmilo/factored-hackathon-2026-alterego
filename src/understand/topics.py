"""
The topics a customer message can carry (TQ-044, decided by Kmilo on 5-Oct; TQ-024 keeps them independent).

A message may state several things at once ("me robaron la tarjeta y hay un cargo que no hice; ¿cuál es mi saldo?").
Each statement is one topic, read on its own: the keyword extractor finds it by clause, and Jev answers one yes or no
question per topic instead of picking a single intent. The conversation takes them one by one in the order of
`criticality` (1 first): the safety of the card, then the dispute of a charge, then a question about the rules, then
whatever this channel does not handle, which the reply names as such. The number of topics is recorded in the signals and
in the audit log, never shown to the customer.

Each definition says what the topic is, what it includes and what it leaves out, in the words Jev is given. Keep them
verbose: the quality of the reading depends on how well the edges are drawn.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    topic_id: str
    criticality: int  # 1 is handled first
    in_scope: bool  # False: this channel does not handle it, and the reply says so
    title_es: str
    title_pt: str
    definition: str
    includes: tuple[str, ...]
    excludes: tuple[str, ...]

    def criteria(self) -> str:
        """The definition as one paragraph for an engine: what it is, what counts and what does not."""
        return (f"{self.definition} Cuenta: {'; '.join(self.includes)}. No cuenta: {'; '.join(self.excludes)}.")


_ALL = (
    Topic("tarjeta_perdida_o_robada", 1, True, "tarjeta perdida o robada", "cartão perdido ou roubado",
          "El cliente dice que ya no tiene su tarjeta física en su poder: la perdió, se la robaron o se la quitaron. Es el tema más "
          "urgente porque alguien más puede estar usándola, y lleva a ofrecer el bloqueo preventivo de la tarjeta.",
          ("\"perdí la tarjeta\"", "\"me robaron la billetera con la tarjeta\"", "\"roubaram meu cartão\"", "\"no encuentro mi tarjeta desde ayer\""),
          ("un cargo que no reconoce cuando conserva la tarjeta", "olvidar el PIN o la clave", "una tarjeta vencida, dañada o que no llegó",
           "pedir una tarjeta nueva sin decir que la perdió")),
    Topic("cargo_no_reconocido", 2, True, "cargo no reconocido", "cobrança não reconhecida",
          "El cliente dice que no hizo o no reconoce un movimiento que aparece en su tarjeta o cuenta: una compra, un retiro, un "
          "pago o una transferencia. Niega haberlo hecho o autorizado.",
          ("\"no reconozco un cargo de 80 dólares\"", "\"vi una compra que no hice\"", "\"não fui eu que fiz essa compra\"",
           "\"en mi extracto hay un movimiento que no es mío\""),
          ("preguntar por sus movimientos o su saldo sin negar ninguno", "reclamar la cuota de un préstamo u otro producto",
           "reconocer la compra y discutir solo el monto o un cobro repetido (eso es cobro indebido)")),
    Topic("cobro_indebido", 2, True, "cobro indebido", "cobrança indevida",
          "El cliente reconoce la compra o el comercio, pero dice que el cobro está mal: se lo cobraron más de una vez, por un monto "
          "distinto al acordado o de más.",
          ("\"me cobraron dos veces la misma compra\"", "\"el monto es incorrecto\"", "\"cobraram duas vezes\"", "\"me cobraron de más\""),
          ("no reconocer la compra en absoluto (eso es cargo no reconocido)", "quejarse de un producto o servicio sin discutir el cobro")),
    Topic("pregunta_sobre_reglas", 3, True, "pregunta sobre las reglas de disputa", "pergunta sobre as regras de contestação",
          "El cliente pregunta cómo funcionan las disputas de cargos, sin referirse a un cargo suyo en particular: plazos, pasos del "
          "proceso, qué movimientos se pueden disputar, cuánto tarda la respuesta, reembolsos o desbloqueo.",
          ("\"¿cuántos días tengo para disputar un cargo?\"", "\"¿qué movimientos puedo reclamar?\"", "\"quanto tempo demora a resposta?\""),
          ("nombrar un cargo propio con monto, fecha o comercio", "preguntar por otro producto del banco")),
    Topic("prestamo_o_credito", 4, False, "préstamos y créditos", "empréstimos e créditos",
          "El cliente pide o pregunta algo sobre un préstamo, un crédito, el cupo o el límite de crédito, o una financiación. Este "
          "canal no lo atiende.",
          ("\"quiero pedir un préstamo\"", "\"aumentar el cupo de mi tarjeta\"", "\"quero um empréstimo\"", "\"la cuota de mi crédito\""),
          ("disputar una compra hecha con la tarjeta de crédito",)),
    Topic("saldo_o_extracto", 4, False, "saldos y extractos", "saldos e extratos",
          "El cliente pide su saldo, su extracto, su estado de cuenta o la lista de sus movimientos, sin disputar ninguno. Este canal "
          "no lo atiende.",
          ("\"¿cuál es mi saldo?\"", "\"dame mi extracto\"", "\"qual é o meu saldo?\"", "\"cuánto tengo en la cuenta\""),
          ("mencionar el extracto como el lugar donde vio un cargo que disputa", "decir el monto de un cargo")),
    Topic("inversion_o_seguro", 4, False, "inversiones y seguros", "investimentos e seguros",
          "El cliente pide o pregunta algo sobre inversiones, CDT, fondos o seguros. Este canal no lo atiende.",
          ("\"quiero invertir\"", "\"información del seguro de vida\"", "\"abrir un CDT\""),
          ("disputar el cobro de una compra cualquiera",)),
    Topic("soporte_de_tarjeta", 4, False, "soporte de tarjeta (PIN, reposición, entrega)", "suporte do cartão (PIN, reposição, entrega)",
          "El cliente pide ayuda con la tarjeta misma y no con un cargo: cambiar u olvidar el PIN o la clave, reposición o segunda "
          "vía, entrega o activación. Este canal no lo atiende.",
          ("\"olvidé el PIN\"", "\"quiero cambiar la clave de la tarjeta\"", "\"esqueci a senha do cartão\"", "\"no me ha llegado la tarjeta nueva\""),
          ("decir que perdió o le robaron la tarjeta (eso es tarjeta perdida o robada)", "disputar un cargo")),
    Topic("otro_producto", 4, False, "otros productos", "outros produtos",
          "El cliente pide o pregunta algo sobre otro producto o servicio del banco que no es una tarjeta ni una cuenta con cargos, o "
          "sobre un tema que ninguna otra definición cubre. Este canal no lo atiende.",
          ("\"abrir una cuenta nueva\"", "\"horarios de la sucursal\"", "\"actualizar mis datos\""),
          ("cualquier disputa de un cargo", "un reporte de tarjeta perdida o robada")),
)

TOPICS: dict[str, Topic] = {t.topic_id: t for t in _ALL}
DISPUTE_TOPICS = ("cargo_no_reconocido", "cobro_indebido")
CARD_TOPIC = "tarjeta_perdida_o_robada"
RULES_TOPIC = "pregunta_sobre_reglas"
OUT_OF_SCOPE_TOPICS = tuple(t.topic_id for t in _ALL if not t.in_scope)
TOPIC_THRESHOLD = 0.5  # a Jev yes at or above this makes the statement a topic; what the policy does with it keeps its own thresholds


def by_criticality(topic_ids: list[str]) -> list[str]:
    """Each topic once, the most critical first; topics of equal criticality keep the order they were given in."""
    seen = list(dict.fromkeys(t for t in topic_ids if t in TOPICS))
    return sorted(seen, key=lambda t: TOPICS[t].criticality)
