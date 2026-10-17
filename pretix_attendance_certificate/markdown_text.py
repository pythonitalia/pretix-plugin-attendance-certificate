"""Markdown for the free text of the text fields of a certificate.

The text of a field is the organizer's template, but it contains placeholders
that pretix replaces by attendee-supplied data (names, ...). Markdown must only
ever come from the *template*: it is parsed here, before pretix substitutes the
placeholders, and turned into a list of blocks whose text carries marker
characters instead of tags. Only after the substitution, ``to_markup`` escapes
everything and turns well-nested markers into reportlab tags. An attendee called
"**x** <b>y</b>" is therefore printed literally.

Supported: paragraphs, headings, (nested) bullet and numbered lists, block
quotes, code, rules, **bold**, *italic*, ++underline++, `code` and
[links](https://example.org).
Images are reduced to their alt text, raw HTML is not interpreted.
"""

import html
import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlparse

import markdown
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe
from markdown.extensions import Extension
from markdown.inlinepatterns import SimpleTagInlineProcessor
from markdown.treeprocessors import Treeprocessor

_PLACEHOLDER = re.compile(r"\{[-a-zA-Z0-9:_]+\}")
_HELD = re.compile("(\\d+)")

# The markers carry a random per-process nonce, so attendee data can't forge them.
_OPEN, _CLOSE = "" + secrets.token_hex(6), ""
_MARKER = re.compile(
    "{}(?P<code>/?[biuc]|/a|a(?P<href>[^{}]*)){}".format(_OPEN, _CLOSE, _CLOSE)
)
_TAGS = {
    "b": ("<b>", "</b>"),
    "i": ("<i>", "</i>"),
    "u": ("<u>", "</u>"),
}
# ++underline++, but not "C++ and C++"
_UNDERLINE = r"(?<![\w+])(\+\+)(?=\S)(.+?)(?<=\S)\+\+(?![\w+])"
_MONO_FONT = re.compile(r"mono|courier|code", re.IGNORECASE)
_ALLOWED_SCHEMES = {"http", "https", "mailto", "tel"}
_BLOCK_TAGS = {"p", "ul", "ol", "li", "blockquote", "pre", "hr"} | {
    "h%d" % n for n in range(1, 7)
}


@dataclass
class Block:
    kind: str  # "p", "h", "pre" or "hr"
    text: str = ""
    level: int = 0  # heading level
    indent: int = 0  # nesting depth of lists and quotes
    marker: str = ""  # bullet or number, on the first block of a list item
    in_list: bool = False  # list items are not separated by a blank line


def _mark(code):
    return _OPEN + code + _CLOSE


class _Capture(Treeprocessor):
    """Keeps the parsed tree, so it doesn't have to be re-read from HTML."""

    root = None

    def run(self, root):
        self.root = root


class _UnderlineExtension(Extension):
    def extendMarkdown(self, md):
        md.inlinePatterns.register(
            SimpleTagInlineProcessor(_UNDERLINE, "u"), "underline", 75
        )


def _parse(source):
    md = markdown.Markdown(extensions=["sane_lists", _UnderlineExtension()])
    md.preprocessors.deregister("html_block")
    for name in ("html", "entity", "automail"):
        md.inlinePatterns.deregister(name)
    md.treeprocessors.deregister("prettify")
    capture = _Capture(md)
    md.treeprocessors.register(capture, "capture", -10)
    md.convert(source)
    return capture.root


def _inline(el, skip=()):
    out = [el.text or ""]
    for child in el:
        if child.tag not in skip:
            out.append(_inline_element(child))
            out.append(child.tail or "")
    return "".join(out)


def _inline_element(el):
    if el.tag == "br":
        return "\n"
    if el.tag == "img":
        return el.get("alt", "")
    inner = _inline(el)
    if el.tag == "strong":
        return _mark("b") + inner + _mark("/b")
    if el.tag == "em":
        return _mark("i") + inner + _mark("/i")
    if el.tag == "u":
        return _mark("u") + inner + _mark("/u")
    if el.tag == "code":
        return _mark("c") + inner + _mark("/c")
    if el.tag == "a":
        return _mark("a" + el.get("href", "")) + inner + _mark("/a")
    return inner


def _walk(parent, blocks, indent, in_list):
    for el in parent:
        if el.tag == "p":
            blocks.append(Block("p", _inline(el), indent=indent, in_list=in_list))
        elif re.fullmatch(r"h[1-6]", el.tag):
            blocks.append(Block("h", _inline(el), level=int(el.tag[1])))
        elif el.tag in ("ul", "ol"):
            _walk_list(el, blocks, indent + 1)
        elif el.tag == "blockquote":
            _walk(el, blocks, indent + 1, in_list)
        elif el.tag == "pre":
            code = el.find("code")
            text = (el.text if code is None else code.text) or ""
            blocks.append(
                Block("pre", _mark("c") + text.rstrip("\n") + _mark("/c"), indent=indent)
            )
        elif el.tag == "hr":
            blocks.append(Block("hr", indent=indent))


def _walk_list(el, blocks, indent):
    number = int(el.get("start", 1)) if el.tag == "ol" else 0
    for item in el:
        marker = "•" if el.tag == "ul" else "{}.".format(number)
        number += 1
        first = len(blocks)
        text = _inline(item, skip=_BLOCK_TAGS)
        if text.strip():
            blocks.append(
                Block("p", text.strip(), indent=indent, marker=marker, in_list=True)
            )
        _walk(item, blocks, indent, True)
        if len(blocks) == first:
            blocks.append(Block("p", "", indent=indent, marker=marker, in_list=True))
        elif not blocks[first].marker:
            blocks[first].marker = marker


def to_blocks(template_text):
    """Template text with Markdown -> list of Blocks, with markers for the
    inline formatting. Placeholders are left as they are."""
    held = []

    def hold(match):
        held.append(match.group(0))
        return "{}".format(len(held) - 1)

    # Placeholders contain underscores, which Markdown would read as emphasis.
    root = _parse(_PLACEHOLDER.sub(hold, template_text))
    blocks = []
    if root is not None:
        _walk(root, blocks, 0, False)
    for block in blocks:
        block.text = _HELD.sub(lambda m: held[int(m.group(1))], block.text)
    return blocks


def _is_safe_url(url):
    return (
        urlparse(url).scheme.lower() in _ALLOWED_SCHEMES
        and not re.search(r"[\s\x00-\x1f]", url)
    )


def find_code_font(fonts):
    """The monospace font among the font families pretix offers, if any. Names
    with a hyphen are skipped: pretix puts a hairspace after every hyphen."""
    for font in fonts:
        if _MONO_FONT.search(font) and "-" not in font:
            return font
    return None


def to_markup(text, code_font=None):
    """Text that may contain markers (and attendee data) -> safe reportlab
    markup. Everything is escaped; only well-nested markers become tags,
    otherwise the text is shown without any formatting. Code is set in
    code_font, or in the font of the field if there is none."""
    tags = dict(_TAGS)
    if code_font:
        tags["c"] = ('<font face="{}">'.format(html.escape(code_font)), "</font>")
    else:
        tags["c"] = ("", "")
    escaped = str(conditional_escape(text))
    out, stack, pos = [], [], 0
    for match in _MARKER.finditer(escaped):
        out.append(escaped[pos : match.start()])
        pos = match.end()
        code = match.group("code")
        if code.startswith("/"):
            if not stack or stack[-1][0] != code:
                return mark_safe(_MARKER.sub("", escaped))
            out.append(stack.pop()[1])
        elif code[0] == "a":
            href = html.unescape(match.group("href")).strip()
            if _is_safe_url(href):
                # pretix puts a hairspace after every hyphen, also inside tags
                url = html.escape(href.replace("-", "%2D"), quote=True)
                out.append('<a href="{}"><u>'.format(url))
                stack.append(("/a", "</u></a>"))
            else:
                stack.append(("/a", ""))
        else:
            out.append(tags[code][0])
            stack.append(("/" + code, tags[code][1]))
    out.append(escaped[pos:])
    if stack:
        return mark_safe(_MARKER.sub("", escaped))
    return mark_safe("".join(out))
