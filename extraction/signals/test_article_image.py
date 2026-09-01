"""Checks for article_image.pick_image.

    python -m pytest extraction/signals/test_article_image.py -q
    python extraction/signals/test_article_image.py          # same checks, no pytest

Every fixture below is a shape taken from a page that is actually in the corpus,
not an invented one -- attribute order, quoting and entity escaping are the three
things real markup varies and hand-written fixtures never do.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from article_image import image_candidates, pick_image      # noqa: E402

BASE = "https://www.example.com/news/story-1"


def test_og_image_plain():
    h = '<head><meta property="og:image" content="https://cdn.ex.com/a.jpg"></head>'
    assert pick_image(h, BASE) == "https://cdn.ex.com/a.jpg"


def test_content_before_property():
    """Half the web writes the attributes the other way round."""
    h = '<meta content="https://cdn.ex.com/b.jpg" property="og:image" />'
    assert pick_image(h, BASE) == "https://cdn.ex.com/b.jpg"


def test_name_instead_of_property():
    h = '<meta name="og:image" content="https://cdn.ex.com/c.jpg">'
    assert pick_image(h, BASE) == "https://cdn.ex.com/c.jpg"


def test_entities_are_unescaped():
    """The bug already in serving.signal_card: `&amp;` reached the CDN literally."""
    h = ('<meta property="og:image" '
         'content="https://pbs.twimg.com/media/G0A?format=jpg&amp;name=small">')
    assert pick_image(h, BASE) == "https://pbs.twimg.com/media/G0A?format=jpg&name=small"


def test_relative_url_resolved():
    h = '<meta property="og:image" content="/img/lead.jpg">'
    assert pick_image(h, BASE) == "https://www.example.com/img/lead.jpg"


def test_protocol_relative_resolved():
    h = '<meta property="og:image" content="//cdn.ex.com/d.jpg">'
    assert pick_image(h, BASE) == "https://cdn.ex.com/d.jpg"


def test_secure_url_wins_over_plain():
    h = ('<meta property="og:image" content="http://cdn.ex.com/plain.jpg">'
         '<meta property="og:image:secure_url" content="https://cdn.ex.com/sec.jpg">')
    assert pick_image(h, BASE) == "https://cdn.ex.com/sec.jpg"


def test_twitter_fallback_when_no_og():
    h = '<meta name="twitter:image" content="https://cdn.ex.com/t.jpg">'
    assert pick_image(h, BASE) == "https://cdn.ex.com/t.jpg"


def test_og_beats_twitter():
    h = ('<meta name="twitter:image" content="https://cdn.ex.com/t.jpg">'
         '<meta property="og:image" content="https://cdn.ex.com/og.jpg">')
    assert pick_image(h, BASE) == "https://cdn.ex.com/og.jpg"


def test_link_image_src():
    h = '<link rel="image_src" href="https://cdn.ex.com/ls.jpg">'
    assert pick_image(h, BASE) == "https://cdn.ex.com/ls.jpg"


def test_json_ld_string():
    h = '<script type="application/ld+json">{"@type":"NewsArticle","image":"https://cdn.ex.com/ld.jpg"}</script>'
    assert pick_image(h, BASE) == "https://cdn.ex.com/ld.jpg"


def test_json_ld_array():
    h = '<script type="application/ld+json">{"image":["https://cdn.ex.com/ld1.jpg","https://cdn.ex.com/ld2.jpg"]}</script>'
    assert pick_image(h, BASE) == "https://cdn.ex.com/ld1.jpg"


def test_json_ld_image_object():
    h = '<script type="application/ld+json">{"image":{"@type":"ImageObject","url":"https://cdn.ex.com/ldo.jpg"}}</script>'
    assert pick_image(h, BASE) == "https://cdn.ex.com/ldo.jpg"


# --- what it must refuse -------------------------------------------------

def test_no_image_returns_none():
    assert pick_image("<html><head><title>x</title></head></html>", BASE) is None


def test_empty_and_none_html():
    assert pick_image("", BASE) is None
    assert pick_image(None, BASE) is None


def test_data_uri_refused():
    h = '<meta property="og:image" content="data:image/png;base64,iVBORw0KGgo=">'
    assert pick_image(h, BASE) is None


def test_svg_refused():
    """Publishers use SVG for chrome; a card showing one looks broken."""
    h = '<meta property="og:image" content="https://cdn.ex.com/brand.svg">'
    assert pick_image(h, BASE) is None


def test_logo_refused():
    h = '<meta property="og:image" content="https://cdn.ex.com/assets/logo.png">'
    assert pick_image(h, BASE) is None


def test_placeholder_and_pixel_refused():
    for bad in ("https://cdn.ex.com/placeholder.jpg",
                "https://cdn.ex.com/img/1x1.gif",
                "https://cdn.ex.com/tracking.gif",
                "https://cdn.ex.com/i/default-image.png"):
        h = '<meta property="og:image" content="%s">' % bad
        assert pick_image(h, BASE) is None, bad


def test_junk_matched_on_path_not_slug():
    """A story whose own slug contains 'logo' must survive."""
    h = '<meta property="og:image" content="https://cdn.ex.com/2026/logos-of-war-lead.jpg">'
    assert pick_image(h, BASE) == "https://cdn.ex.com/2026/logos-of-war-lead.jpg"


def test_falls_through_junk_to_next_candidate():
    """A logo in og:image must not cost us the real twitter:image."""
    h = ('<meta property="og:image" content="https://cdn.ex.com/logo.png">'
         '<meta name="twitter:image" content="https://cdn.ex.com/real-lead.jpg">')
    assert pick_image(h, BASE) == "https://cdn.ex.com/real-lead.jpg"


def test_relative_without_base_refused():
    """No base URL means we cannot build something a browser can fetch."""
    assert pick_image('<meta property="og:image" content="/img/a.jpg">', "") is None


def test_candidates_deduplicated():
    h = ('<meta property="og:image" content="https://cdn.ex.com/a.jpg">'
         '<meta name="twitter:image" content="https://cdn.ex.com/a.jpg">')
    assert image_candidates(h, BASE) == ["https://cdn.ex.com/a.jpg"]


def test_body_images_ignored():
    """Only <head> is scanned, so related-story thumbnails cannot win."""
    h = ('<head><title>t</title></head><body>'
         '<img src="https://cdn.ex.com/related-thumb.jpg"></body>')
    assert pick_image(h, BASE) is None


# --- regressions found by running against the real corpus ----------------

def test_og_image_type_is_not_a_url():
    """`og:image:type` carries "image/jpeg". Matching og:image as a prefix read
    it as a URL and wrote thedefensepost.com/2026/06/25/image/jpeg to a card."""
    h = ('<meta property="og:image:type" content="image/jpeg">'
         '<meta property="og:image" content="https://cdn.ex.com/real.jpg">')
    assert pick_image(h, BASE) == "https://cdn.ex.com/real.jpg"


def test_og_image_width_not_taken():
    h = ('<meta property="og:image:width" content="1200">'
         '<meta property="og:image:height" content="630">')
    assert pick_image(h, BASE) is None


def test_og_image_alt_not_taken():
    h = '<meta property="og:image:alt" content="A tank on a range">'
    assert pick_image(h, BASE) is None


def test_unquoted_key_still_matches():
    h = '<meta property=og:image content="https://cdn.ex.com/u.jpg">'
    assert pick_image(h, BASE) == "https://cdn.ex.com/u.jpg"


def test_numeric_camera_filename_kept():
    """analisidifesa.it: a date-stamped photo with a CDN resize suffix. Every
    token is numeric, but it is the article's own picture."""
    h = ('<meta property="og:image" content='
         '"https://ex.com/wp-content/uploads/2024/04/20240110_125758-360x245.jpg">')
    assert pick_image(h, BASE) == \
        "https://ex.com/wp-content/uploads/2024/04/20240110_125758-360x245.jpg"


def test_short_numeric_filename_kept():
    h = '<meta property="og:image" content="https://ex.com/u/2-360x245.jpg">'
    assert pick_image(h, BASE) == "https://ex.com/u/2-360x245.jpg"


def test_bare_size_still_refused():
    for bad in ("https://ex.com/i/1x1.gif", "https://ex.com/i/300x250.png"):
        assert pick_image('<meta property="og:image" content="%s">' % bad, BASE) is None, bad


def test_social_share_image_refused():
    """rusi.org offered /images/social.png -- site furniture, on every article."""
    h = '<meta property="og:image" content="https://www.rusi.org/images/social.png">'
    assert pick_image(h, BASE) is None


def test_twitter_profile_icon_refused():
    h = ('<meta property="og:image" content='
         '"https://ex.com/uploads/Twitter-Profile-Icon-400x400-1-1024x1024-1.jpg">')
    assert pick_image(h, BASE) is None


def test_janes_default_source_path_kept():
    """`/default-source/` is a Sitefinity convention, not a placeholder."""
    h = ('<meta property="og:image" content='
         '"https://www.janes.com/images/default-source/news-images/bsp_114183-jdw-37074.jpeg">')
    assert pick_image(h, BASE) == \
        "https://www.janes.com/images/default-source/news-images/bsp_114183-jdw-37074.jpeg"


def test_numeric_entity_unescaped():
    """globaldefensecorp: `&#038;ssl=1` reached the CDN literally."""
    h = ('<meta property="og:image" content='
         '"https://i0.wp.com/ex.com/a.png?fit=1200%2C675&#038;ssl=1">')
    assert pick_image(h, BASE) == "https://i0.wp.com/ex.com/a.png?fit=1200%2C675&ssl=1"


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print("  ok   %s" % name)
        except AssertionError as e:
            fails += 1
            print("  FAIL %s  %s" % (name, e))
    print("\n%s" % ("all checks passed" if not fails else "%d FAILED" % fails))
    sys.exit(1 if fails else 0)
