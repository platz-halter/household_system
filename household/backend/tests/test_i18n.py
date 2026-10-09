"""Guards the server-side notification/report translation dictionary
(household_service.i18n) against the one mistake a flat dict like this
is prone to: adding an English string and forgetting its German
counterpart (or vice versa) — t() would silently fall back to English
for that one key rather than failing loudly, so this is the only thing
that would actually catch it.
"""

import string

from household_service.i18n import _STRINGS, t


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def test_every_key_has_both_languages():
    missing = {key: {"en", "de"} - set(langs) for key, langs in _STRINGS.items()}
    missing = {key: langs for key, langs in missing.items() if langs}
    assert not missing, f"keys missing a language: {missing}"


def test_every_entry_is_non_empty():
    empty = [
        f"{key}.{lang}"
        for key, langs in _STRINGS.items()
        for lang, text in langs.items()
        if not text.strip()
    ]
    assert not empty, f"empty translations: {empty}"


def test_placeholders_match_between_languages():
    """A mistyped {param} in just one language's template would otherwise
    only raise KeyError for recipients of that one language, inside a
    live notify path - this catches it at test time instead."""
    mismatched = {
        key: {"en": _placeholders(langs["en"]), "de": _placeholders(langs["de"])}
        for key, langs in _STRINGS.items()
        if _placeholders(langs["en"]) != _placeholders(langs["de"])
    }
    assert not mismatched, f"mismatched placeholders: {mismatched}"


def test_t_substitutes_params():
    assert t("en", "chain_task.body", parent="Set the table", child="Clear the table") == (
        'After "Set the table": Clear the table'
    )
    assert t("de", "verb.accepted") == "angenommen"


def test_t_falls_back_to_english_for_unknown_language():
    # Not a real call site today (only "en"/"de" ever reach this), but
    # the fallback chain itself is worth pinning down.
    assert t("fr", "nudge.title") == _STRINGS["nudge.title"]["en"]
