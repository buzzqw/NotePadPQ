from pathlib import Path

from core.markdown_features import (
    expand_wikilinks_for_preview,
    extract_headings,
    extract_wikilinks,
    find_backlinks,
    generate_toc,
    insert_or_update_toc,
    is_image_url,
    smart_paste_markdown,
    validate_mermaid,
    wikilink_at,
)


def test_toc_ignores_fences_and_disambiguates_duplicate_slugs():
    text = "# Intro\n\n## API\n\n```\n# Not a heading\n```\n\n## API\n"
    assert generate_toc(text) == (
        "- [Intro](#intro)\n"
        "  - [API](#api)\n"
        "  - [API](#api-1)"
    )
    assert [h.line for h in extract_headings(text)] == [1, 3, 9]


def test_toc_insert_and_update_preserves_markers():
    text = "# One\n\n## Two\n"
    result = insert_or_update_toc(text, cursor=0)
    assert result.updated is False
    assert "<!-- TOC -->" in result.text
    updated = insert_or_update_toc(result.text.replace("## Two", "## Three"))
    assert updated.updated is True
    assert "#three" in updated.text
    assert "#two" not in updated.text


def test_wikilinks_and_context_lookup():
    text = "See [[notes/today|today]] and [[other]]."
    links = extract_wikilinks(text)
    assert links[0].target == "notes/today"
    assert links[0].label == "today"
    assert wikilink_at(text, text.index("today")).target == "notes/today"


def test_wikilinks_are_rendered_as_preview_links_but_code_stays_untouched():
    text = "See [[notes/today|today]].\n\n```\n[[not-a-link]]\n```\n"
    rendered = expand_wikilinks_for_preview(text)
    assert "[today](npq-wikilink:notes%2Ftoday)" in rendered
    assert "[[not-a-link]]" in rendered


def test_backlinks_resolve_relative_markdown_files(tmp_path: Path):
    target = tmp_path / "target.md"
    source = tmp_path / "source.md"
    target.write_text("# Target", encoding="utf-8")
    source.write_text("See [[target]].", encoding="utf-8")
    assert find_backlinks([source, target], target) == [source]


def test_smart_paste_links_and_images():
    assert smart_paste_markdown("https://example.test", "Ferrite") == "[Ferrite](https://example.test)"
    assert smart_paste_markdown("https://example.test/a.png?size=1") == "![](https://example.test/a.png?size=1)"
    assert smart_paste_markdown("plain text", "Ferrite") is None
    assert is_image_url("https://example.test/a.SVG#view")


def test_mermaid_validation_is_offline_and_non_destructive():
    assert validate_mermaid("```mermaid\nflowchart TD\n A --> B\n```") == []
    errors = validate_mermaid("```mermaid\nunknownDiagram\n```")
    assert errors and "non riconosciuto" in errors[0]
