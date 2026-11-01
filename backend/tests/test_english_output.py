"""English-only application output (AGENTS.md, Rules): API, AI layer and data messages.

Every string literal in the application package is a possible user-facing message (error
texts, validation reasons, CLI output). None may hold French or Portuguese text. Names and
figures are not concerned: this guard only looks for common French and Portuguese words
and letters with French or Portuguese accents.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import dealpilot

PACKAGE = Path(dealpilot.__file__).parent
# Common French and Portuguese words that are not English words.
NON_ENGLISH_WORDS = re.compile(
    r"(?i)\b(le|les|des|une|est|pas|avec|pour|dans|sur|aucun|aucune|erreur|donn[ée]es|"
    r"ventes|veuillez|introuvable|nao|não|dados|erro|vendas|uma|você|voce|está|senha|"
    r"obrigatório|inválido|invalide|requête|requete|réponse|resposta)\b")
ACCENTED = re.compile(r"[àâäçéèêëîïôöùûüÿœæãõáíóú]", re.IGNORECASE)


def _strings(source: str) -> list[str]:
    """String literals, including the fixed parts of f-strings."""
    return [node.value for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)]


# insights/language.py holds the French and Portuguese indicator words of the spec 005 D6
# check on purpose; they are detection data, never shown to a user.
INDICATOR_LISTS = PACKAGE / "insights" / "language.py"
SOURCES = sorted(p for p in PACKAGE.rglob("*.py")
                 if "__pycache__" not in p.parts and p != INDICATOR_LISTS)


def test_english_only_messages_of_the_language_rules() -> None:
    """The one excluded file: its user-facing texts are still English."""
    from dealpilot.insights.language import ENGLISH_INSTRUCTION, PROMPT_LEAD

    for text in (ENGLISH_INSTRUCTION, PROMPT_LEAD):
        assert not (NON_ENGLISH_WORDS.search(text) or ACCENTED.search(text)), text


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.relative_to(PACKAGE).as_posix())
def test_english_only_messages_in_application_code(path: Path) -> None:
    found = [text for text in _strings(path.read_text(encoding="utf-8"))
             if NON_ENGLISH_WORDS.search(text) or ACCENTED.search(text)]
    assert not found, found


def test_english_only_guard_catches_french_and_portuguese() -> None:
    """Control: the guard does flag French and Portuguese, and passes English messages."""
    for text in ("Erreur : les données sont introuvables.", "Não foi possível ler os dados.",
                 "Requête invalide"):
        assert NON_ENGLISH_WORDS.search(text) or ACCENTED.search(text), text
    for text in ("The request has an invalid parameter.", "usage ledger is busy",
                 "content blocked by the provider", "Dates must be inside the dataset range."):
        assert not (NON_ENGLISH_WORDS.search(text) or ACCENTED.search(text)), text
