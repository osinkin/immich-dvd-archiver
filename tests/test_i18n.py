from __future__ import annotations

from immich_dvd import i18n
from immich_dvd.i18n import _STRINGS, SUPPORTED, set_language, t


def test_translation_catalogues_have_the_same_keys() -> None:
    assert set(_STRINGS["ru"]) == set(_STRINGS["en"])


def test_formatting_and_fallback() -> None:
    set_language("en")
    assert t("cli.est_discs", value=3) == "Discs: 3"
    set_language("ru")
    assert t("cli.est_discs", value=3) == "Дисков: 3"
    assert t("missing.key") == "missing.key"


def test_unknown_language_falls_back_to_english() -> None:
    assert set_language("de") == "en"
    assert set_language("") == "en"
    assert set_language("ru") == "ru"


def test_byte_units_follow_language() -> None:
    set_language("ru")
    assert i18n.byte_units()[1] == "КиБ"
    set_language("en")
    assert i18n.byte_units()[1] == "KiB"


def test_supported_languages() -> None:
    assert SUPPORTED == ("ru", "en")
