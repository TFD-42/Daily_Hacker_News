"""Translation + English-first rendering.

Locks in the behaviour that the whole journal reads in English:
  - a translated title (`title_en`) is what the card/markdown/JSON show,
  - non-English summaries are replaced by their English translation,
  - no dual-language clutter (native + English) is emitted,
  - English-source articles are left untouched.

These tests never hit a translation backend — they set `title_en` /
`summary_en` directly (as the real pipeline does) and assert on the render.
"""
from __future__ import annotations

import json


def test_translated_title_wins_in_card(make_article, secjournal):
    a = make_article(theme="News-FR", lang="fr",
                     title="Multiples vulnérabilités dans Google Chrome",
                     title_en="Multiple vulnerabilities in Google Chrome",
                     summary="De multiples vulnérabilités ont été découvertes.",
                     summary_en="Multiple vulnerabilities have been discovered.")
    card = secjournal._build_card(a)
    assert "Multiple vulnerabilities in Google Chrome" in card
    # original French title must not appear as the visible headline
    assert "Multiples vulnérabilités dans Google Chrome" not in card
    # English-first: French summary must not be shown alongside the English one
    assert "De multiples vulnérabilités" not in card
    assert "Multiple vulnerabilities have been discovered." in card
    # no dual-language flags
    assert "🇫🇷" not in card and "🇬🇧" not in card


def test_english_source_untouched(make_article, secjournal):
    a = make_article(theme="News-EN", lang="en",
                     title="Critical RCE in Acme Widget",
                     summary="An unauthenticated attacker can run code.")
    card = secjournal._build_card(a)
    assert "Critical RCE in Acme Widget" in card
    assert "An unauthenticated attacker can run code." in card


def test_store_record_uses_english(make_article, secjournal):
    a = make_article(theme="News-CN", lang="zh",
                     title="超越提示词",
                     title_en="Beyond the prompt",
                     summary_en="A jailbreak technique.")
    rec = secjournal._art_to_record(a, "News-CN")
    assert rec["title"] == "Beyond the prompt"      # display title is English
    assert rec["title_orig"] == "超越提示词"           # original preserved
    assert rec["lang"] == "zh"
    # record must be JSON-serialisable (goes to the JSONL store)
    json.dumps(rec, ensure_ascii=False)


def test_markdown_uses_english_title(make_article, secjournal):
    a = make_article(theme="News-FR", lang="fr",
                     title="Faille critique",
                     title_en="Critical flaw",
                     summary_en="Patch now.")
    md = secjournal.render_md({"News-FR": [a]},
                              type("Args", (), {"days": 1})(), 1)
    assert "Critical flaw" in md
    assert "Faille critique" not in md
