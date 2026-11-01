"""Spec 005 D6: English-only rules for AI explanations (AC-SUM-11 to AC-SUM-14).

Implemented under the limited exception of AGENTS.md (2026-10-31) while spec 005 stays
Draft. Synthetic facts, fake replies and the real mock provider only: no network, no key.
"""
from __future__ import annotations

import copy
import json

import pytest

from dealpilot.ai import CompletionRequest, get_provider, load_settings
from dealpilot.ai.gemini import GeminiProvider
from dealpilot.insights.language import (
    ENGLISH,
    ENGLISH_INSTRUCTION,
    NON_ENGLISH,
    PROMPT_LEAD,
    UNCERTAIN,
    detect_language,
    language_messages,
    review_explanation,
)

# Synthetic facts with French and Portuguese names, as a metrics result could hold.
FACTS = {
    "range": "2025-01-01 to 2025-01-31",
    "totals": {"units": 7935, "revenue": "2026466.37", "orders": 2354},
    "top_category": {"name": "Boissons et Café Crème", "share_percent": "47.7"},
    "bottom_category": {"name": "Hygiène", "share_percent": "3.7"},
    "top_region": {"name": "São Paulo das Vendas", "share_percent": "31.2"},
    "top_product": "Pão de Queijo",
}
FACTS_JSON = json.dumps(FACTS, ensure_ascii=False)
SUMMARY = ("From 2025-01-01 to 2025-01-31: 7,935 units and 2,026,466.37 revenue from 2,354 "
           "orders.")  # stands for the fixed English template summary of spec 005

ENGLISH_REPLY = ("Boissons et Café Crème leads revenue with 47.7% of the total, while Hygiène "
                 "is the lowest with 3.7%. São Paulo das Vendas is the top region and Pão de "
                 "Queijo is the top product.")
FRENCH_REPLY = ("Les ventes de la catégorie Boissons et Café Crème sont en tête avec 47,7 % du "
                "chiffre d'affaires, et Hygiène est la plus faible avec 3,7 %.")
PORTUGUESE_REPLY = ("As vendas da categoria Boissons et Café Crème lideram com 47,7% da "
                    "receita, e a Hygiène é a mais baixa com 3,7%. Não houve queda.")


def _feature(reply: str) -> dict:
    """Stand-in for the future spec 005 result: only the D6 part is real."""
    review = review_explanation(reply, [FACTS_JSON])
    return {"facts": FACTS, "summary": SUMMARY, "ai_explanation": review.explanation,
            "ai_status": review.status}


# --------------------------------------------------------------------------- AC-SUM-11

@pytest.mark.parametrize("system_text", ["", "Use only the numbers in the facts."])
@pytest.mark.parametrize("facts_json", [FACTS_JSON, "{}", '{"name": "Ventes du mois"}'])
def test_ac_sum_11_prompt_holds_the_language_rules(system_text, facts_json) -> None:
    system, user = language_messages(system_text, facts_json)
    assert (system.role, user.role) == ("system", "user")
    assert ENGLISH_INSTRUCTION in system.content
    assert system.content.startswith(ENGLISH_INSTRUCTION)
    assert ENGLISH_INSTRUCTION == (
        "Respond in English only. Use clear, professional business English. Preserve all "
        "supplied figures, names, dates, categories and business meaning exactly. Do not "
        "translate, recalculate, invent or modify numerical results.")
    assert user.content.startswith(PROMPT_LEAD + "\n")
    assert user.content.endswith(facts_json)  # the facts are passed through unchanged


def test_ac_sum_11_mock_reply_passes_with_non_english_names() -> None:
    """French or Portuguese input data never turns the mock reply into a rejection."""
    request = CompletionRequest(list(language_messages("", FACTS_JSON)))
    reply = get_provider(load_settings({})).complete(request).text
    assert review_explanation(reply, [FACTS_JSON]).status == "ok"


def test_ac_sum_11_provider_stays_language_neutral() -> None:
    """Spec 006 section 10: no language rule inside the Gemini provider."""
    import inspect

    source = inspect.getsource(GeminiProvider)
    assert "English" not in source and "insights" not in source


# --------------------------------------------------------------------------- AC-SUM-12

@pytest.mark.parametrize("reply", [FRENCH_REPLY, PORTUGUESE_REPLY])
def test_ac_sum_12_french_or_portuguese_reply_is_rejected(reply) -> None:
    assert detect_language(reply, [FACTS_JSON]) == NON_ENGLISH
    facts_before = copy.deepcopy(FACTS)
    rejected = _feature(reply)
    accepted = _feature(ENGLISH_REPLY)
    assert (rejected["ai_status"], rejected["ai_explanation"]) == ("rejected", None)
    assert rejected["facts"] == accepted["facts"] == facts_before
    assert rejected["summary"] == accepted["summary"] == SUMMARY


# --------------------------------------------------------------------------- AC-SUM-13

@pytest.mark.parametrize("reply", [
    "Revenue rose.",                                       # too few English indicators
    "47.7% / 3.7%",                                        # figures only
    "",                                                    # nothing to judge
    "The total of the month is high, with les orders up.",  # one foreign indicator
    "The revenue of the region was strong and stable, très good.",  # accents only
])
def test_ac_sum_13_uncertain_reply_is_rejected(reply) -> None:
    assert detect_language(reply, [FACTS_JSON]) == UNCERTAIN
    result = _feature(reply)
    assert (result["ai_status"], result["ai_explanation"]) == ("rejected", None)
    assert result["summary"] == SUMMARY


# --------------------------------------------------------------------------- AC-SUM-14

@pytest.mark.parametrize("reply", [
    ENGLISH_REPLY,
    ("Revenue was 2,026,466.37 from 2,354 orders, and the top region was São Paulo das "
     "Vendas with 31.2% of the total."),
    ("Pão de Queijo is the top product of the month, with Boissons et Café Crème as the "
     "leading category."),
])
def test_ac_sum_14_english_reply_with_foreign_names_is_kept(reply) -> None:
    assert detect_language(reply, [FACTS_JSON]) == ENGLISH
    result = _feature(reply)
    assert result["ai_status"] == "ok"
    assert result["ai_explanation"] == reply  # never translated or edited


def test_ac_sum_14_names_count_only_when_they_are_in_the_facts() -> None:
    """The same words outside the facts are indicators: no hidden allowlist."""
    reply = "Boissons et Café Crème leads revenue with 47.7% of the total."
    assert detect_language(reply, [FACTS_JSON]) == ENGLISH
    assert detect_language(reply, []) != ENGLISH


# Facts whose keys and values hold English function words ("to", "of", "the").
WORDY_FACTS = json.dumps({"range": "2025-01-01 to 2025-01-31", "share_of_the_total": "31.2",
                          "top_of_the_range": "Pão de Queijo", "region": "São Paulo das Vendas"},
                         ensure_ascii=False)


@pytest.mark.parametrize("reply", [
    "Sales went to the top of the range.",  # the audit's false rejection, word for word
    "Revenue of the top region rose to 31.2% of the total.",
    "The share of the total went to Pão de Queijo in the range.",
    "São Paulo das Vendas rose to the top of the regions.",
])
def test_ac_sum_14_english_words_in_the_facts_still_count(reply) -> None:
    """Regression: English function words that also appear in the facts are not ignored."""
    assert detect_language(reply, [WORDY_FACTS]) == ENGLISH
    assert review_explanation(reply, [WORDY_FACTS]).explanation == reply  # unchanged


@pytest.mark.parametrize("reply", [
    "As vendas das lojas subiram no mês, com a receita de Pão de Queijo em alta.",
    "Les ventes de la région São Paulo das Vendas sont en hausse.",
])
def test_ac_sum_12_foreign_reply_reusing_fact_words_is_rejected(reply) -> None:
    """Fact names stay ignored, but the rest of a foreign reply still gives it away."""
    assert review_explanation(reply, [WORDY_FACTS]).status == "rejected"


@pytest.mark.parametrize(("reply", "expected"), [
    ("Las ventas de la categoría crecieron en enero.", NON_ENGLISH),  # Spanish
    ("Le vendite della categoria sono cresciute a gennaio.", NON_ENGLISH),  # Italian
    ("Der Umsatz ist im Januar gestiegen.", UNCERTAIN),  # German: no indicators at all
])
def test_ac_sum_13_other_languages_are_rejected(reply, expected) -> None:
    assert detect_language(reply, [FACTS_JSON]) == expected
    assert review_explanation(reply, [FACTS_JSON]).status == "rejected"


def test_ac_sum_12_detection_classes() -> None:
    assert {detect_language(FRENCH_REPLY), detect_language(PORTUGUESE_REPLY)} == {NON_ENGLISH}
    assert detect_language("The sales of the region were stable over the month.") == ENGLISH
