#!/usr/bin/env python3
"""Render docs/WHITEPAPER.md and docs/PRESENTATION.md to PDF, deterministically.

WHY THIS EXISTS
---------------
The publication package needs PDFs a reader can download and a release-evidence step
can hash. Two off-the-shelf pieces cover that without pulling in a publishing platform:
`markdown` turns the committed Markdown into HTML, and WeasyPrint lays that HTML out as
a paginated PDF from plain CSS. No browser, no headless-Chrome dependency, no JavaScript
build step -- both are declared in `pyproject.toml`'s `docs` extra.

WeasyPrint itself binds against system Pango/cairo/GDK-Pixbuf via cffi. That native
dependency is real and worth stating rather than hiding: `pip install -e '.[docs]'`
installs the Python side; the underlying text-shaping libraries have to already be on
the machine (Homebrew's `weasyprint` formula pulls them on macOS; most Linux
distributions package them as `libpango-1.0-0` / `libcairo2` / `libgdk-pixbuf-2.0-0`).

Run it:  .venv/bin/python docs/build_pdfs.py
Output:  docs/WHITEPAPER.pdf, docs/PRESENTATION.pdf

DETERMINISM
-----------
Same Markdown in, same PDF bytes out, modulo two things WeasyPrint stamps from the
environment: the PDF `CreationDate`/`ModifyDate` and, if the host's fonts differ, glyph
substitution. Neither is disguised here -- `--pdf-variant` is not used and no attempt is
made to strip timestamps, because a document claiming byte-reproducibility it does not
have would be worse than one that says plainly what varies.
"""
from __future__ import annotations

import pathlib
import re
import sys

import markdown as md
from weasyprint import HTML

DOCS = pathlib.Path(__file__).resolve().parent
ROOT = DOCS.parent

MD_EXTENSIONS = ["tables", "fenced_code", "sane_lists", "attr_list", "footnotes"]

BASE_CSS = """
@page {
    size: A4;
    margin: 22mm 20mm 24mm 20mm;
    @bottom-center {
        content: counter(page) " / " counter(pages);
        font-family: "Iowan Old Style", "Georgia", serif;
        font-size: 9pt;
        color: #6b6b6b;
    }
}
html { font-family: "Iowan Old Style", "Palatino", "Georgia", serif; color: #1a1a1a; }
body { font-size: 10.5pt; line-height: 1.5; }
h1, h2, h3, h4 { font-family: "Helvetica Neue", "Arial", sans-serif; color: #14213d;
                 line-height: 1.25; break-after: avoid; }
h1 { font-size: 20pt; margin-top: 0; border-bottom: 2pt solid #14213d; padding-bottom: 6pt; }
h2 { font-size: 14pt; margin-top: 20pt; border-top: 0.5pt solid #cccccc; padding-top: 10pt; }
h3 { font-size: 11.5pt; margin-top: 14pt; }
h4 { font-size: 10.5pt; margin-top: 10pt; }
p { margin: 6pt 0; orphans: 3; widows: 3; }
blockquote { margin: 10pt 0; padding: 4pt 12pt; border-left: 3pt solid #ca8a04;
             background: #fdf8ee; font-style: italic; }
code, pre, kbd { font-family: "SF Mono", "Menlo", "Consolas", monospace; }
code { background: #f2f1ec; padding: 1pt 3pt; font-size: 9pt; border-radius: 2pt; }
pre { background: #1a1a1a; color: #f2f1ec; padding: 9pt 11pt; font-size: 8.5pt;
      line-height: 1.4; border-radius: 3pt; white-space: pre-wrap; word-wrap: break-word;
      break-inside: avoid; }
pre code { background: none; padding: 0; color: inherit; }
table { border-collapse: collapse; width: 100%; margin: 10pt 0; font-size: 9pt;
        break-inside: avoid; }
th, td { border: 0.5pt solid #b9b9b9; padding: 4pt 7pt; text-align: left;
         vertical-align: top; }
th { background: #14213d; color: #ffffff; font-family: "Helvetica Neue", sans-serif;
     font-weight: 600; }
tr:nth-child(even) td { background: #f7f6f2; }
hr { border: none; border-top: 0.5pt solid #cccccc; margin: 14pt 0; }
a { color: #9a6a00; text-decoration: none; }
ul, ol { margin: 4pt 0 4pt 16pt; padding: 0; }
li { margin: 2pt 0; }
strong { color: #14213d; }
.title-block { text-align: center; margin-bottom: 4pt; }
.title-block h1 { border-bottom: none; font-size: 24pt; }
.title-block .subtitle { font-family: "Helvetica Neue", sans-serif; color: #4a4a4a;
                          font-size: 12pt; margin-top: -4pt; }
.title-block .byline { font-style: italic; color: #6b6b6b; font-size: 10pt; }
"""

SLIDE_CSS = """
@page {
    size: 297mm 167mm;
    margin: 14mm 16mm;
    @bottom-right {
        content: counter(page);
        font-family: "Helvetica Neue", "Arial", sans-serif;
        font-size: 9pt;
        color: #9a9a9a;
    }
}
html { font-family: "Helvetica Neue", "Arial", sans-serif; color: #1a1a1a; }
body { font-size: 13pt; line-height: 1.35; }
section.slide { break-after: page; min-height: 100%; }
section.slide:last-of-type { break-after: avoid; }
h1 { font-size: 26pt; color: #14213d; margin: 0 0 4pt 0; }
h2 { font-size: 20pt; color: #14213d; margin: 0 0 12pt 0; border-bottom: 1.5pt solid #ca8a04;
     padding-bottom: 6pt; }
h3 { font-size: 15pt; color: #14213d; margin: 10pt 0 4pt 0; }
p { margin: 5pt 0; }
blockquote { margin: 8pt 0; padding: 6pt 12pt; border-left: 3pt solid #ca8a04;
             background: #fdf8ee; font-style: italic; font-size: 13pt; }
code, pre { font-family: "SF Mono", "Menlo", "Consolas", monospace; }
pre { background: #14213d; color: #f2f1ec; padding: 8pt 10pt; font-size: 10.5pt;
      line-height: 1.4; border-radius: 3pt; white-space: pre-wrap; word-wrap: break-word; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 10.5pt; }
th, td { border: 0.5pt solid #b9b9b9; padding: 4pt 8pt; text-align: left; vertical-align: top; }
th { background: #14213d; color: #ffffff; }
tr:nth-child(even) td { background: #f7f6f2; }
hr { display: none; }
.deck-title { text-align: center; }
.deck-title h1 { font-size: 34pt; text-align: center; }
.deck-title .subtitle { text-align: center; font-size: 16pt; color: #4a4a4a; margin-top: 4pt; }
.deck-title .byline { text-align: center; font-style: italic; color: #6b6b6b;
                       margin-top: 24pt; font-size: 11pt; }
strong { color: #14213d; }
"""


def render_whitepaper() -> None:
    src = (DOCS / "WHITEPAPER.md").read_text()
    body = md.markdown(src, extensions=MD_EXTENSIONS)
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{BASE_CSS}</style>" \
           f"</head><body>{body}</body></html>"
    HTML(string=html, base_url=str(DOCS)).write_pdf(DOCS / "WHITEPAPER.pdf")
    print("wrote docs/WHITEPAPER.pdf")


def render_presentation() -> None:
    src = (DOCS / "PRESENTATION.md").read_text()
    # Slides are separated by a Markdown thematic break ('---' alone on a line). The
    # title block above the first '---' becomes its own slide.
    parts = re.split(r"\n-{3,}\n", src)
    slides_html = []
    for i, part in enumerate(parts):
        part = part.strip("\n")
        if not part.strip():
            continue
        cls = "deck-title" if i == 0 else ""
        body = md.markdown(part, extensions=MD_EXTENSIONS)
        slides_html.append(f"<section class='slide {cls}'>{body}</section>")
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{SLIDE_CSS}</style></head><body>{''.join(slides_html)}</body></html>"
    )
    HTML(string=html, base_url=str(DOCS)).write_pdf(DOCS / "PRESENTATION.pdf")
    print(f"wrote docs/PRESENTATION.pdf ({len(slides_html)} slides)")


def main() -> int:
    render_whitepaper()
    render_presentation()
    return 0


if __name__ == "__main__":
    sys.exit(main())
