"""
Keyword and regex extractor for Spanish and Portuguese dispute messages.

This is the default Understand engine, the fallback when Jev has no key, and the baseline Jev is measured
against (docs/JEV_TYPESAFE_AI.md). It fills the same typed contract Jev fills; confidence fields stay
None because a keyword match carries no calibrated probability. Amount and date hints are extracted from
the raw text before PII masking, because the masker turns a 7-digit COP amount into a phone (SEC-05).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.rules.dispute_policy import STOLEN_CARD_KEYWORDS

PT_MARKERS = ("não", "nao ", "você", "voce", "cartão", "cartao", "cobrança", "cobranca", "estou", "obrigad", "reconheço",
              "reconheco", "compra que", "ontem", "hoje", "fiz", "quero", "minha", "meu ", "uma ", "isso", "também", "ção")
ES_MARKERS = ("no reconozco", "cargo", "tarjeta", "estoy", "gracias", "ayer", "hoy", "hice", "quiero", "mi ", "una ", "eso",
              "también", "ción", "ñ", "cobro", "compra que no")

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "cobro_indebido": ("cobro doble", "cobraron dos veces", "dos veces", "cobro indebido", "monto incorrecto", "me cobraron de más",
                       "me cobraron de mas", "cobraram duas vezes", "duas vezes", "cobrança indevida", "cobranca indevida",
                       "valor errado", "valor incorreto", "cobrado a mais"),
    "cargo_no_reconocido": ("no reconozco", "no hice", "no realicé", "no realice", "cargo que no", "no fui yo", "desconozco",
                            "no autoricé", "no autorice", "não reconheço", "nao reconheco", "não fiz", "nao fiz", "não fui eu",
                            "nao fui eu", "não autorizei", "nao autorizei", "desconheço", "desconheco", "compra que não",
                            "compra que nao", "cobrança estranha", "cobranca estranha", "cargo extraño", "cargo extrano",
                            "no es mío", "no es mio", "no es mía", "no es mia", "no son míos", "no son mios", "no son mías",
                            "no son mias", "não é meu", "nao e meu", "não é minha", "nao e minha", "não são meus", "nao sao meus",
                            "não são minhas", "nao sao minhas"),
}
OUT_OF_SCOPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "prestamo_o_credito": ("préstamo", "prestamo", "crédito hipotecario", "credito hipotecario", "empréstimo", "emprestimo",
                           "financiamiento", "financiamento", "cupo de crédito", "cupo de credito", "aumentar el cupo", "aumento de límite",
                           "aumento de limite", "limite do cartão", "limite do cartao"),
    "saldo_o_extracto": ("mi saldo", "meu saldo", "extracto", "extrato", "estado de cuenta", "cuánto tengo", "cuanto tengo",
                         "quanto tenho", "movimientos de mi cuenta"),
    "inversion_o_seguro": ("inversión", "inversion", "invertir", "investimento", "investir", "seguro de vida", "seguro del auto",
                           "seguro do carro", "cdt", "fondo de inversión"),
    "soporte_de_tarjeta": ("cambiar el pin", "cambiar mi pin", "olvidé el pin", "olvide el pin", "clave de la tarjeta", "reposición",
                           "reposicion", "reposição", "reposicao", "segunda vía", "segunda via", "nueva tarjeta", "novo cartão",
                           "novo cartao", "entrega de la tarjeta", "activar la tarjeta", "desbloquear el pin", "trocar a senha"),
}

# Answers to the lock question (accents stripped). LOCK_CARD needs the customer's confirmation (ACTION_AUTH_MATRIX): a yes locks
# only when every word of the answer says yes, a no refuses only when it refuses, and a question, a doubt or both at once is asked
# again. "No hay problema" or "cómo no" say yes, "no importa" says neither; a word that only starts like one ("Sigo", "Podemos")
# says nothing.
LOCK_YES_PHRASES = ("no hay problema", "no tengo problema", "nao tem problema", "tudo bem", "esta bien", "por supuesto",
                    "com certeza", "como no", "de acuerdo", "de una")
LOCK_NEUTRAL_PHRASES = ("no importa", "nao importa")
LOCK_YES_WORDS = frozenset({"si", "sim", "claro", "dale", "ok", "okay", "okey", "vale", "listo", "confirmo", "adelante", "procede",
                            "proceda", "hazlo", "hagalo", "pode", "podem", "isso", "correcto", "exacto", "afirmativo", "perfecto", "bloquear",
                            "bloquea", "bloquee", "bloqueen", "bloqueala", "bloqueela", "bloqueenla", "bloquearla", "bloqueia", "bloqueie",
                            "bloqueiem"})
LOCK_YES_FILLER = frozenset({"por", "favor", "porfa", "porfavor", "la", "lo", "el", "a", "o", "tarjeta", "cartao", "ya", "ja", "ahora",
                             "agora", "mismo", "gracias", "obrigado", "obrigada", "seguro", "una", "vez"})
LOCK_UNSURE_RE = re.compile(r"[?¿]|\b(?:no\s+se|nao\s+sei|no\s+estoy\s+segur[oa]|nao\s+tenho\s+certeza|tal\s+vez|talvez|quizas?)\b")
LOCK_REFUSAL_RE = re.compile(
    r"^\W*(?:no|nao|nop|nope|negativo|nel)\W*$|^\W*(?:no|nao)\s*[,.;!]|"
    r"\b(?:no|nao)\s+(?:gracias|obrigad[oa]|me\s+interesa|me\s+interessa|hace\s+falta|precisa)\b|"
    r"\b(?:no|nao)\s+(?:quiero|quero|deseo|desejo)\s*(?:$|[,.;!]|(?:nada|gracias|obrigad[oa])\b)|"  # a want refuses alone, not with its reason
    r"\b(?:mejor|ahora|agora|todavia|ainda)\s+(?:no|nao)\b|\b(?:prefiero|prefiro)\s+(?:que\s+)?(?:no|nao)\b|\bclaro\s+que\s+(?:no|nao)\b|"
    r"\bpara\s+nada\b|\bnem\s+pensar\b|\bde\s+jeito\s+nenhum\b|\bdeixa\s+quieto\b|\bdejalo\s+asi\b|"
    r"\b(?:no|nao|nunca)\s+(?:(?:la|lo|me|te|se|a|o|que|quiero|quero|deseo|desejo|vayan|van|vai)\s+){0,4}bloqu\w*")  # "no quiero que me la bloqueen"
AFFIRMED_LOCK_RE = re.compile(r"\b(?:bloqueala|bloqueela|bloqueenla|bloquearla|bloqueia|bloqueie|bloqueiem|pode\s+bloquear)\b")
BARE_YES_RE = re.compile(r"\b(?:si+|sim+)\b")
LOCK_UNREADABLE_RE = re.compile(r"[^\w\s.,;:!¡'\"’‘“”()-]")  # an emoji or sign the vocabulary cannot read ("sí ❌")
# Closed vocabulary around a reply to the numbered candidate list (accents stripped). No negation, preposition or unit
# belongs here, so "no es el 2", "el 2 de junio", "2 dólares" or "2 mil" never read as an option.
OPTION_REPLY_WORDS = frozenset({
    "el", "la", "a", "o", "es", "e", "era", "seria", "sera", "fue", "foi", "opcion", "opcao", "numero", "nro", "n",
    "movimiento", "movimento", "cargo", "cobro", "cobranca", "compra", "quiero", "quero", "elijo", "escojo", "escolho",
    "selecciono", "seleciono", "si", "sim", "ok", "por", "favor", "gracias", "obrigado", "obrigada",
})
OPTION_TOKEN_RE = re.compile(r"[^\s.,;:!?¡¿()#º°ª]+")  # "/", "$" and "-" stay inside a token: "2/6" and "$2" are not options

AMOUNT_RE = re.compile(
    r"(?<![\w.])(?:\$|usd\s?|us\$\s?|cop\s?|ars\s?|r\$\s?)?\s*(\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,](\d{1,2}))?\s*"
    r"(dólares|dolares|dólar|dolar|usd|pesos|cop|ars|reais|reales|mil)?",
    re.IGNORECASE,
)
DAY_MONTH_RE = re.compile(r"\b(\d{1,2})\s+de\s+([a-záéíóúç]+)\b", re.IGNORECASE)
NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b")
DAYS_AGO_RE = re.compile(r"\b(?:hace|há|ha|faz)\s+(\d{1,2})\s+d[ií]as?\b", re.IGNORECASE)
MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
    "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "maio": 5, "junho": 6, "julho": 7, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


# All on accent-stripped text. The loss and theft words are the policy's own (S8), matched as whole words ("aprobaron" is no theft).
LOSS_RE = re.compile(r"\b(?:" + "|".join(re.escape(_strip_accents(k)) for k in STOLEN_CARD_KEYWORDS) + r")\b")
# Words that name one charge: the disputable types of POL-DISP-TYPE (purchase, payment, withdrawal, transfer) and a statement line.
# A payment or a transfer is also something the customer makes ("no hice el pago a tiempo"), so a loose phrase never refers to one.
CORE_CHARGE_NOUNS = r"cargos?|cobr\w*|compras?|transac\w*|movimientos?|movimentos?|debitos?|retiros?|saques?|lancamentos?"
CHARGE_NOUNS = rf"{CORE_CHARGE_NOUNS}|transferencias?|pagos?|pagamentos?"
CHARGE_NOUN_RE = re.compile(rf"\b(?:{CHARGE_NOUNS})\b")
CORE_CHARGE_NOUN_RE = re.compile(rf"\b(?:{CORE_CHARGE_NOUNS})\b")
CURRENCY_AMOUNT_RE = re.compile(r"(?:\$|us\$|r\$)\s*\d|\d[\d.,]*\s*(?:mil\s+)?(?:dolares|dolar|usd|pesos|cop|ars|reais|reales)\b")
BALANCE_RE = re.compile(r"\bsaldos?\b")  # "mi saldo de 80 dólares": the amount of a balance names no charge
LIST_GAP_RE = re.compile(r"\s*(?:,|y|e|o|ou)?\s*")  # what separates the amounts of one list: "45, 80 y 120 dólares"
CHARGE_CUE_RE = re.compile(rf"\b(?:{CHARGE_NOUNS}|usaron|usaram|utilizaron|utilizaram|gastaron|gastaram|sacaron|sacaram|retiraron|"
                           r"compraron|compraram|debitaron|debitaram)\b")  # a charge or a use of the card is told, not money alone
DISPUTE_PHRASES = tuple(dict.fromkeys(_strip_accents(w) for words in INTENT_KEYWORDS.values() for w in words))
LOOSE_DISPUTE_PHRASES = ("no hice", "no realice", "nao fiz", "dos veces", "duas vezes")  # dispute a charge only when said after it
NOT_A_DISPUTE_RE = re.compile(r"\b(?:desconozco|desconheco)\s+(?:como|cuanto|cuando|donde|que|quanto|quando|onde)\b")  # not knowing how
CLAUSE_SPLIT_RE = re.compile(r"((?<!\d)[.,]|[.,](?!\d)|[;!?¿¡]|\b(?:y|(?<!\bnao )e|pero|porem|porque|pois|aunque|embora)\b)")  # never in "85.000" or "não é"
DATE_EXPR_RE = re.compile(r"\b(?:anteayer|antier|anteontem|ayer|ontem|hoy|hoje|(?:hace|ha|faz)\s+\d{1,2}\s+dias?|semana\s+pasada|"
                          r"semana\s+passada|\d{1,2}\s+de\s+[a-z]+|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b")
DATE_FILLER_WORDS = frozenset({"el", "la", "lo", "los", "las", "o", "a", "os", "as", "no", "na", "en", "em", "de", "del", "do", "da", "dia",
                               "fue", "foi", "era", "por", "tarde", "noche", "manana", "noite", "manha", "madrugada", "mediodia"})


@dataclass
class UnderstandResult:
    language: str = "es"
    intent: str = "consulta_general"
    intent_confidence: float | None = None  # keyword matches carry no calibrated probability
    out_of_scope_category: str | None = None
    amount_hint: float | None = None
    amount_hints: list[float] = field(default_factory=list)  # every charge amount the message names, in order
    currency_hint: str | None = None
    date_hint: date | None = None
    date_tolerance_days: int = 0
    stolen_card_claimed: bool = False
    said_yes: bool = False
    said_no: bool = False
    selected_option: int | None = None
    matched_keywords: list[str] = field(default_factory=list)
    message_lower: str = ""
    stolen_card_probability: float | None = None  # Jev Noul; None means keyword fallback inside the policy
    distress_score: float | None = None  # Jev Score; None means keyword fallback inside the policy
    engine: str = "keyword"
    model: str | None = None
    request_id: str | None = None
    tokens_in: int = 0

    def as_signals(self) -> dict:
        return {
            "language": self.language, "intent": self.intent, "intent_confidence": self.intent_confidence,
            "out_of_scope_category": self.out_of_scope_category, "amount_hint": self.amount_hint, "amount_hints": self.amount_hints,
            "currency_hint": self.currency_hint, "date_hint": self.date_hint.isoformat() if self.date_hint else None,
            "date_tolerance_days": self.date_tolerance_days, "stolen_card_claimed": self.stolen_card_claimed,
            "said_yes": self.said_yes, "said_no": self.said_no, "selected_option": self.selected_option,
            "stolen_card_probability": self.stolen_card_probability, "distress_score": self.distress_score,
            "extractor": self.engine, "model": self.model, "request_id": self.request_id,
        }


class KeywordIntentExtractor:
    """Deterministic ES/PT extractor. `today` is the dataset anchor date, not the wall clock."""

    name = "keyword-v1"

    def __init__(self, today: date = date(2026, 6, 17)):
        self.today = today

    def extract(self, text: str) -> UnderstandResult:
        raw = text or ""
        low = raw.lower()
        low_plain = _strip_accents(low)
        result = UnderstandResult(language=self.detect_language(low), message_lower=low)
        result.selected_option = self.option_reply(raw)
        result.stolen_card_claimed = any(k in low for k in STOLEN_CARD_KEYWORDS)

        disputed = any(self._disputes_a_charge(c) for c in CLAUSE_SPLIT_RE.split(low_plain)[::2])
        for category, words in OUT_OF_SCOPE_KEYWORDS.items():
            if disputed and category == "saldo_o_extracto":
                continue  # the statement is where a disputed charge shows up: naming it does not make the request out of scope
            hit = next((w for w in words if w in low), None)
            if hit:
                result.intent, result.out_of_scope_category = "fuera_de_alcance", category
                result.matched_keywords.append(hit)
                break
        if result.intent != "fuera_de_alcance":
            for intent, words in INTENT_KEYWORDS.items():
                hit = next((w for w in words if w in low), None)
                if hit:
                    result.intent = intent
                    result.matched_keywords.append(hit)
                    break
            if result.intent == "consulta_general" and result.stolen_card_claimed:
                result.intent = "tarjeta_robada"

        result.amount_hint, result.currency_hint = self._amount(raw)
        result.amount_hints = self._amounts(raw)
        result.date_hint, result.date_tolerance_days = self._charge_date(low_plain)
        result.said_yes, result.said_no = self._lock_answer(low_plain)
        if result.intent == "consulta_general" and (result.amount_hint is not None or "cargo" in low_plain
                                                    or "cobranca" in low_plain or "compra" in low_plain):
            result.intent = "cargo_no_reconocido"
        return result

    @staticmethod
    def detect_language(low: str) -> str:
        pt = sum(low.count(m) for m in PT_MARKERS)
        es = sum(low.count(m) for m in ES_MARKERS)
        return "pt" if pt > es else "es"

    @staticmethod
    def option_reply(text: str) -> int | None:
        """A reply to the numbered candidate list: exactly one digit 1-9, every other word from the closed vocabulary."""
        tokens = OPTION_TOKEN_RE.findall(_strip_accents((text or "").lower()))
        digits = [t for t in tokens if re.fullmatch(r"[1-9]", t)]
        if len(digits) != 1 or any(t not in OPTION_REPLY_WORDS for t in tokens if t not in digits):
            return None
        return int(digits[0])

    @staticmethod
    def _parse_amount(m: re.Match, raw: str) -> tuple[float, str | None, bool, int]:
        """One AMOUNT_RE match: its value, its currency, whether a currency marks it, and how many digits it has."""
        whole, dec, unit = m.group(1), m.group(2), (m.group(3) or "").lower()
        prefix = raw[max(0, m.start() - 4):m.start()].lower()
        has_currency = bool(unit) or "$" in raw[max(0, m.start() - 1):m.end()] or "usd" in prefix or "cop" in prefix or "ars" in prefix
        digits = whole.replace(".", "").replace(",", "")
        value = float(digits)
        if dec and not (len(whole) >= 5 and whole[-4] in ".," and dec and len(dec) == 3):
            value = float(f"{digits}.{dec}")
        if unit == "mil":
            value *= 1000
        currency = None
        if unit in ("dólares", "dolares", "dólar", "dolar", "usd") or "usd" in prefix or "us$" in prefix:
            currency = "USD"
        elif unit == "cop" or "cop" in prefix:
            currency = "COP"
        elif unit == "ars" or "ars" in prefix:
            currency = "ARS"
        elif unit in ("pesos",):
            currency = "PESOS"
        elif unit in ("reais", "reales"):
            currency = "BRL"
        return value, currency, has_currency, len(digits)

    @classmethod
    def _amount(cls, raw: str) -> tuple[float | None, str | None]:
        best: tuple[float, str | None] | None = None
        for m in AMOUNT_RE.finditer(raw):
            value, currency, has_currency, digits = cls._parse_amount(m, raw)
            if not has_currency and digits < 2:
                continue
            if best is None or has_currency:
                best = (value, currency)
                if has_currency:
                    break
        return (best[0], best[1]) if best else (None, None)

    @classmethod
    def _amounts(cls, raw: str) -> list[float]:
        """Every charge amount the message names, in order: each one with a currency, and the unit-less ones of a list that
        ends in one ("45, 80 y 120 dólares"). A date is no amount, and the amount of a balance names no charge."""
        low = raw.lower()
        found: list[float] = []
        pending: list[float] = []
        previous_end = 0
        for m in AMOUNT_RE.finditer(raw):
            value, _, has_currency, digits = cls._parse_amount(m, raw)
            if pending and not LIST_GAP_RE.fullmatch(low[previous_end:m.start()]):
                pending = []
            previous_end = m.end()
            if BALANCE_RE.search(cls._clause_at(low, m.start())):
                pending = []
            elif has_currency:
                found += pending + [value]
                pending = []
            elif digits >= 2:
                pending.append(value)
        return list(dict.fromkeys(found))

    @staticmethod
    def _clause_at(low: str, pos: int) -> str:
        """The clause (CLAUSE_SPLIT_RE) that holds the character at pos."""
        start = max((m.end() for m in CLAUSE_SPLIT_RE.finditer(low, 0, pos)), default=0)
        end = CLAUSE_SPLIT_RE.search(low, pos)
        return low[start:end.start() if end else len(low)]

    @classmethod
    def _lock_answer(cls, low_plain: str) -> tuple[bool, bool]:
        """Yes or no to the lock question (see LOCK_YES_WORDS): a closed yes locks, a refusal refuses, the rest is asked again.
        The refusal is read without the dispute phrases, so the "no" of "no reconozco un cargo" refuses nothing."""
        if LOCK_UNSURE_RE.search(low_plain):
            return False, False
        refuses = LOCK_REFUSAL_RE.search(cls._without_dispute_phrases(low_plain)) is not None
        yes_text = low_plain
        for phrase in LOCK_YES_PHRASES:
            yes_text = yes_text.replace(phrase, " si ")
        for phrase in LOCK_NEUTRAL_PHRASES:
            yes_text = yes_text.replace(phrase, " ")
        known = LOCK_YES_WORDS | LOCK_YES_FILLER
        words = [w if w in known else re.sub(r"(.)\1+", r"\1", w) for w in re.findall(r"[a-z0-9]+", yes_text)]  # "siii", "okk"
        says_yes = (any(w in LOCK_YES_WORDS for w in words) and all(w in known for w in words)
                    and not LOCK_UNREADABLE_RE.search(low_plain))
        if says_yes and not refuses:
            return True, False
        # a refusal next to a lock imperative or a bare yes ("No, bloquéala", "Sí, no gracias") contradicts itself: asked again
        if refuses and not says_yes and not cls._affirms_lock(low_plain) and not BARE_YES_RE.search(low_plain):
            return False, True
        return False, False

    @staticmethod
    def _affirms_lock(low_plain: str) -> bool:
        """A lock imperative ("bloquéala", "pode bloquear") that no "no" just before negates."""
        return any(not {"no", "nao", "nunca"} & set(low_plain[:m.start()].split()[-3:]) for m in AFFIRMED_LOCK_RE.finditer(low_plain))

    @staticmethod
    def _without_dispute_phrases(low_plain: str) -> str:
        for phrase in DISPUTE_PHRASES:
            low_plain = low_plain.replace(phrase, " ")
        return low_plain

    @staticmethod
    def _disputes_a_charge(clause: str) -> bool:
        """A clause that names one charge and disputes it: "un pago que no reconozco", never "no hice el pago a tiempo"."""
        clause = NOT_A_DISPUTE_RE.sub(" ", clause)
        amount = None if BALANCE_RE.search(clause) else CURRENCY_AMOUNT_RE.search(clause)
        if not (CHARGE_NOUN_RE.search(clause) or amount):
            return False
        core = [m.start() for m in (CORE_CHARGE_NOUN_RE.search(clause), amount) if m]
        after = clause[min(core):] if core else ""
        return any(p in (after if p in LOOSE_DISPUTE_PHRASES else clause) for p in DISPUTE_PHRASES)

    @staticmethod
    def _only_a_date(clause: str) -> bool:
        """"Ayer", "el 5 de junio", "no dia 5 de junho": a clause that holds a date and nothing else."""
        rest = DATE_EXPR_RE.sub(" ", clause)
        return rest != clause and all(w in DATE_FILLER_WORDS for w in rest.split())

    def _charge_date(self, low_plain: str) -> tuple[date | None, int]:
        """The date of the charge, never the day of a loss or theft: when a loss is told, only the clauses that tell a charge
        and no loss are read. A date on its own opens the clause after it when a comma follows ("Ayer, me robaron..."), and
        otherwise belongs to the sentence before it ("... . Fue ayer.")."""
        if not LOSS_RE.search(low_plain):
            return self._date(low_plain)
        parts = CLAUSE_SPLIT_RE.split(low_plain)
        clauses: list[str] = []
        carry = ""
        for i in range(0, len(parts), 2):
            clause, sep = parts[i], (parts[i + 1] if i + 1 < len(parts) else "")
            if self._only_a_date(clause):
                if sep == ",":
                    carry = f"{carry} {clause}"
                    continue
                if clauses:
                    clauses[-1] = f"{clauses[-1]} {clause}"
                    continue
            clauses.append(f"{carry} {clause}")
            carry = ""
        told = [c for c in clauses if not LOSS_RE.search(c) and (CHARGE_CUE_RE.search(c) or self._disputes_a_charge(c))]
        return self._date(" . ".join(told))  # the separator keeps a day and a month apart

    def _date(self, low_plain: str) -> tuple[date | None, int]:
        today = self.today
        if "anteayer" in low_plain or "antier" in low_plain or "anteontem" in low_plain:
            return today - timedelta(days=2), 1
        if "ayer" in low_plain or "ontem" in low_plain:
            return today - timedelta(days=1), 1
        if re.search(r"\bhoy\b|\bhoje\b", low_plain):
            return today, 1
        m = DAYS_AGO_RE.search(low_plain)
        if m:
            return today - timedelta(days=int(m.group(1))), 1
        if "semana pasada" in low_plain or "semana passada" in low_plain:
            return today - timedelta(days=10), 5
        m = DAY_MONTH_RE.search(low_plain)
        if m and m.group(2) in MONTHS:
            day, month = int(m.group(1)), MONTHS[m.group(2)]
            year = today.year if (month, day) <= (today.month, today.day) else today.year - 1
            try:
                return date(year, month, day), 1
            except ValueError:
                return None, 0
        m = NUMERIC_DATE_RE.search(low_plain)
        if m:
            day, month = int(m.group(1)), int(m.group(2))
            year = int(m.group(3)) if m.group(3) else today.year
            if year < 100:
                year += 2000
            try:
                return date(year, month, day), 1
            except ValueError:
                return None, 0
        return None, 0
