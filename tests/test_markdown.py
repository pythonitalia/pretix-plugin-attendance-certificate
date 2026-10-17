import json
from io import BytesIO

import pytest
from django_scopes import scopes_disabled

from pretix_attendance_certificate.markdown_text import (
    _mark,
    find_code_font,
    to_blocks,
    to_markup,
)
from pretix_attendance_certificate.render import render_certificate


def _markup(text):
    return [to_markup(b.text) for b in to_blocks(text)]


def test_inline_formatting():
    assert _markup("**b** *i* `c`") == ["<b>b</b> <i>i</i> c"]


def test_underline():
    assert _markup("++u++ and **++both++**") == ["<u>u</u> and <b><u>both</u></b>"]


def test_plus_signs_are_not_underline():
    assert _markup("C++ and C++, 1 ++ 2 ++ 3") == ["C++ and C++, 1 ++ 2 ++ 3"]


def test_underline_markers_in_substituted_data_are_literal():
    text = to_blocks("{attendee_name}")[0].text
    assert to_markup(text.replace("{attendee_name}", "++x++")) == "++x++"


def test_code_uses_the_monospace_font_if_there_is_one():
    text = to_blocks("`c`")[0].text
    assert to_markup(text, "Fira Mono") == '<font face="Fira Mono">c</font>'


def test_find_code_font():
    assert find_code_font(["Open Sans", "Fira Mono", "Other"]) == "Fira Mono"
    assert find_code_font(["Open Sans", "Fira-Mono", "Courier Prime"]) == "Courier Prime"
    assert find_code_font(["Open Sans", "Other"]) is None


def test_blank_line_separates_paragraphs_and_newline_stays():
    blocks = to_blocks("one\ntwo\n\nthree")
    assert [b.kind for b in blocks] == ["p", "p"]
    assert blocks[0].text == "one\ntwo"


def test_lists():
    blocks = to_blocks("- a\n- b\n    - c\n\n1. x\n2. y")
    assert [(b.marker, b.indent, b.text) for b in blocks] == [
        ("•", 1, "a"),
        ("•", 1, "b"),
        ("•", 2, "c"),
        ("1.", 1, "x"),
        ("2.", 1, "y"),
    ]


def test_sane_lists_keep_the_start_number():
    assert to_blocks("3. x\n4. y")[0].marker == "3."


def test_headings():
    block = to_blocks("## Title")[0]
    assert (block.kind, block.level, block.text) == ("h", 2, "Title")


def test_links():
    assert _markup("[x](https://a-b.de/?q=1&r=2)") == [
        '<a href="https://a%2Db.de/?q=1&amp;r=2"><u>x</u></a>'
    ]
    assert _markup("[x](mailto:a@b.de)") == ['<a href="mailto:a@b.de"><u>x</u></a>']


@pytest.mark.parametrize("url", ["javascript:alert(1)", "example.com", "file:///etc/passwd"])
def test_links_with_other_schemes_are_text_only(url):
    assert _markup("[x]({})".format(url)) == ["x"]


def test_images_are_reduced_to_their_alt_text():
    assert _markup("![the alt](x.png)") == ["the alt"]


def test_html_is_not_interpreted():
    assert _markup("<b>x</b> &amp; <div>y</div>") == [
        "&lt;b&gt;x&lt;/b&gt; &amp;amp; &lt;div&gt;y&lt;/div&gt;"
    ]


def test_placeholders_survive_underscores():
    assert to_blocks("{attendee_name} and {a_b_c}")[0].text == "{attendee_name} and {a_b_c}"


def test_markup_in_substituted_data_is_literal():
    text = to_blocks("Hi {attendee_name}, **welcome**")[0].text
    data = '**x** <b>y</b> [a](http://evil.example) - z'
    assert to_markup(text.replace("{attendee_name}", data)) == (
        "Hi **x** &lt;b&gt;y&lt;/b&gt; [a](http://evil.example) - z, <b>welcome</b>"
    )


def test_markers_in_substituted_data_cannot_be_forged():
    text = to_blocks("{attendee_name}")[0].text
    forged = "bbold/b"
    assert "<b>" not in to_markup(text.replace("{attendee_name}", forged))


def test_badly_nested_markers_fall_back_to_plain_text():
    assert to_markup(_mark("b") + "a" + _mark("/i")) == "a"
    assert to_markup(_mark("b") + "a") == "a"
    assert to_markup("a" + _mark("/b")) == "a"


def _field(text, bottom, type_="textarea", **extra):
    field = {
        "type": type_, "left": "20", "bottom": str(bottom), "fontsize": "14",
        "color": [0, 0, 0, 1], "fontfamily": "Open Sans", "bold": False, "italic": False,
        "width": "150", "content": "other", "text": text, "align": "left",
        "lineheight": 1,
    }
    if type_ == "textcontainer":
        field.update(height="60", verticalalign="top", autoresize=True)
    field.update(extra)
    return field


def _render(layout, pos, event, fields):
    pypdf = pytest.importorskip("pypdf")
    with scopes_disabled():
        layout.layout = json.dumps(fields)
        layout.save()
        pdf = render_certificate(position=pos, event=event, layout=layout)
    return pypdf.PdfReader(BytesIO(pdf.read())).pages[0]


@pytest.mark.django_db
@pytest.mark.parametrize("type_", ["textarea", "textcontainer"])
def test_lists_headings_and_links_are_drawn(event, pos, layout, type_):
    page = _render(
        layout, pos, event,
        [_field(
            "# Course\n\nDear {attendee_name},\n\n- first\n- second\n\n"
            "[the site](https://example.org/a-b)",
            250, type_,
        )],
    )
    text = page.extract_text()
    for expected in ("Course", "Dear Marco Acierno,", "first", "second", "the site"):
        assert expected in text
    assert "•" in text
    uris = [a.get_object().get("/A", {}).get("/URI") for a in page.get("/Annots", [])]
    assert uris == ["https://example.org/a%2Db"]


@pytest.mark.django_db
def test_attendee_data_is_printed_literally(event, pos, layout):
    with scopes_disabled():
        pos.attendee_name_parts = {"_legacy": "**x** <b>y</b> [a](http://evil.example)"}
        pos.save()
    page = _render(layout, pos, event, [_field("{attendee_name}", 250)])
    assert "**x** <b>y</b> [a](http://evil.example)" in page.extract_text()
    assert "/Annots" not in page


@pytest.mark.django_db
def test_plain_text_is_unchanged(event, pos, layout):
    page = _render(layout, pos, event, [_field("Just text\nsecond line", 250)])
    assert "Just text\nsecond line" in page.extract_text()


@pytest.mark.django_db
def test_list_bullet_is_on_the_first_line_of_a_multiline_item(event, pos, layout):
    page = _render(
        layout, pos, event,
        [_field("- Entwicklung der Jugendarbeit im Verein", 250, width="40")],
    )
    lines = []
    page.extract_text(
        visitor_text=lambda text, cm, tm, font, size: lines.append((text.strip(), tm[5] + cm[5]))
        if text.strip() else None
    )
    ys = dict(lines)
    assert len({y for _, y in lines}) > 1  # the item wraps
    assert ys["•"] == max(y for _, y in lines)
    assert ys["•"] == ys["Entwicklung"]
