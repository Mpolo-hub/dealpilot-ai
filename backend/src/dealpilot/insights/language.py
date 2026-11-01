"""English-only rules for AI explanations (spec 005 D6, section 7).

DealPilot is English-only (AGENTS.md). The AI providers stay language-neutral (spec 006
section 10); this module holds the feature-level rules instead:
- `ENGLISH_INSTRUCTION`, the text the fixed system message must hold word for word;
- `PROMPT_LEAD`, the fixed English sentence the user message starts with, so the mock
  provider's reply (which repeats the prompt) is English too;
- `detect_language` and `review_explanation`, the local heuristic check.

The check only decides. It never translates or edits the AI text, and it never touches the
facts, the summary or any figure. It is a heuristic, not a language identification: it can
reject a correct but very short English text (the safe side), and it can accept a language
it has no indicators for. Standard library only.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from dealpilot.ai.types import Message

ENGLISH_INSTRUCTION = (
    "Respond in English only. Use clear, professional business English. Preserve all "
    "supplied figures, names, dates, categories and business meaning exactly. Do not "
    "translate, recalculate, invent or modify numerical results."
)
PROMPT_LEAD = ("Explain these sales facts for a business manager, using only the figures in "
               "the JSON block below.")

ENGLISH = "english"
NON_ENGLISH = "non_english"
UNCERTAIN = "uncertain"
MIN_ENGLISH_INDICATORS = 3  # section 7, D6 rule 3

# Common English function words that are not French or Portuguese words.
ENGLISH_WORDS = frozenset({
    "the", "and", "of", "with", "from", "was", "were", "is", "are", "in", "to", "for",
    "by", "at", "than", "this", "that", "these", "those", "its", "it", "which", "has",
    "had", "have", "while", "over", "between", "each", "their", "most", "least", "into",
    "after", "before", "during", "compared", "both", "also", "only",
})
# Common French and Portuguese words that are not English words. Words shared with
# English ("a", "on", "no", "do", "plus", "total") are left out on purpose.
NON_ENGLISH_WORDS = frozenset({
    # French
    "le", "la", "les", "des", "du", "une", "et", "est", "sont", "avec", "pour", "dans",
    "sur", "aux", "au", "ces", "cette", "leur", "mais", "qui", "pas", "nous", "vous",
    "ventes", "mois", "chiffre", "affaires", "hausse", "baisse", "de", "en", "été",
    "était", "par", "selon",
    # Portuguese
    "não", "nao", "uma", "com", "para", "vendas", "dos", "das", "foi", "são", "sao",
    "pelo", "pela", "mês", "mes", "também", "tambem", "que", "por", "em", "na",
    "da", "receita", "crescimento", "queda",
})
_WORD = re.compile(r"[^\W\d_]+")  # letter sequences: digits and figures never count
_ACCENTED = re.compile(r"[àâäçéèêëîïôöùûüÿœæãõáíóú]")


def words(text: str) -> list[str]:
    """Section 7, D6 rule 1: the letter sequences of `text`, lowercased."""
    return _WORD.findall(text.lower())


def detect_language(text: str, ignore: Iterable[str] = ()) -> str:
    """Return `english`, `non_english` or `uncertain` (section 7, D6 rules 1 to 4).

    `ignore` holds the texts of the facts (names, categories, regions, filters, dates):
    their words never count, so a French or Portuguese product name can't reject an
    English reply. English function words are the exception: they always count, even when
    they also appear in the facts (for example "to" in a date range or "of" in a JSON key),
    so the facts can't hide the English of a reply.
    """
    ignored = {word for item in ignore for word in words(item)} - ENGLISH_WORDS
    counted = [word for word in words(text) if word not in ignored]
    english = sum(word in ENGLISH_WORDS for word in counted)
    foreign = sum(word in NON_ENGLISH_WORDS for word in counted)
    if any(_ACCENTED.search(word) and word not in NON_ENGLISH_WORDS for word in counted):
        foreign += 1  # accents alone never decide: one indicator at most
    if english >= MIN_ENGLISH_INDICATORS and foreign == 0:
        return ENGLISH
    if foreign >= 2 or foreign > english:
        return NON_ENGLISH
    return UNCERTAIN


@dataclass(frozen=True)
class Review:
    """`explanation` is the unchanged AI text, or None when rejected."""

    explanation: str | None
    status: str  # "ok" or "rejected" (spec 005 section 5)


def review_explanation(ai_text: str, fact_texts: Iterable[str]) -> Review:
    """Keep the AI text only when it is clearly English; otherwise reject it (D6 rule 4).

    On rejection the caller returns its fixed English summary and the facts unchanged;
    nothing here translates, edits or recomputes anything.
    """
    if detect_language(ai_text, fact_texts) == ENGLISH:
        return Review(ai_text, "ok")
    return Review(None, "rejected")


def language_messages(system_text: str, facts_json: str) -> tuple[Message, Message]:
    """The two prompt messages with the D6 rules: the instruction first in the system
    message, and the user message starting with `PROMPT_LEAD` before the facts."""
    system = ENGLISH_INSTRUCTION if not system_text else f"{ENGLISH_INSTRUCTION}\n{system_text}"
    return Message("system", system), Message("user", f"{PROMPT_LEAD}\n{facts_json}")
