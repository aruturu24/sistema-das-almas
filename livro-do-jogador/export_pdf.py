# -*- coding: utf-8 -*-
"""Export livro-do-jogador.md → PDF (Markdown → HTML → Chromium)."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import markdown
from markdown.extensions.md_in_html import MarkdownInHtmlExtension

ROOT = Path(__file__).resolve().parent
MD_PATH = ROOT / "livro-do-jogador.md"
CSS_PATH = ROOT / "styles" / "livro.css"
HTML_PATH = ROOT / "livro-do-jogador.html"
PDF_PATH = ROOT / "livro-do-jogador.pdf"
IMG = ROOT / "images"


COVER_HTML = f"""
<section class="cover">
  <img class="cover-bg" src="{IMG.as_uri()}/capa-sistema-das-almas.jpg" alt=""/>
  <div class="cover-veil"></div>
  <div class="cover-content">
    <div class="cover-kicker">✦ Roleplaying Game ✦</div>
    <h1>Sistema das Almas</h1>
    <p class="cover-subtitle">Livro do Jogador</p>
    <div class="cover-rule"></div>
    <p class="cover-tag">Crie, teste regras, anote o que falhou.</p>
    <p class="cover-edition">Edição Alpha · Playtest</p>
  </div>
</section>
"""

ORNAMENT = f'<img class="ornament" src="{IMG.as_uri()}/ornamento-capitulo.png" alt=""/>'


def figure(filename: str, caption: str) -> str:
    return (
        f'<figure class="figure">'
        f'<img src="{IMG.as_uri()}/{filename}" alt="{caption}"/>'
        f"<figcaption>{caption}</figcaption>"
        f"</figure>"
    )


def strip_front_matter(md_text: str) -> str:
    return re.sub(r"^---\n.*?\n---\n", "", md_text, count=1, flags=re.S)


def clean_source(md_text: str) -> str:
    """Remove broken titlepage / pagebreak div wrappers; keep content."""
    text = strip_front_matter(md_text)
    # Drop entire titlepage block (cover is injected in HTML)
    text = re.sub(
        r'<div class="titlepage">[\s\S]*?</div>\s*',
        "",
        text,
        count=1,
    )
    text = re.sub(r'<div class="pagebreak"></div>\s*', "\n\n", text)
    # Drop old sumário title — we rebuild a nicer TOC header
    return text


def enhance_html(html: str) -> str:
    # Wrap body content (except we rebuild full doc later)
    # Chapter ornaments after each h1
    def chap(m: re.Match) -> str:
        title = m.group(1)
        raw = re.sub(r"<[^>]+>", "", title).strip()
        upper = raw.upper()
        if upper.startswith("CAPÍTULO") or upper.startswith("CAPITULO"):
            # "CAPÍTULO 1: FOO" → label + rest
            parts = re.split(r":\s*", raw, maxsplit=1)
            if len(parts) == 2:
                label, rest = parts
                inner = f'<span class="chap-label">{label}</span>{rest}'
            else:
                inner = raw
            return f'<h1 class="chapter-title">{inner}</h1>\n{ORNAMENT}\n'
        if upper.startswith("APÊNDICE") or upper.startswith("APENDICE"):
            parts = re.split(r":\s*", raw, maxsplit=1)
            if len(parts) == 2:
                label, rest = parts
                inner = f'<span class="chap-label">{label}</span>{rest}'
            else:
                inner = raw
            return f'<h1 class="chapter-title">{inner}</h1>\n{ORNAMENT}\n'
        if upper in ("PARTE 1", "PARTE 2"):
            return f'<h1 class="part-title">{raw}</h1>\n{ORNAMENT}\n'
        if upper == "SUMÁRIO" or upper == "SUMARIO":
            return f"<h1>{raw}</h1>\n{ORNAMENT}\n"
        if upper in ("PREFÁCIO", "PREFACIO", "INTRODUÇÃO", "INTRODUCAO"):
            return f"<h1>{raw}</h1>\n{ORNAMENT}\n"
        return m.group(0)

    html = re.sub(r"<h1>(.*?)</h1>", chap, html, flags=re.S)

    # Insert illustrations after specific headings (anchors must be unique)
    html = html.replace(
        "<h2>Os Três Pilares</h2>",
        "<h2>Os Três Pilares</h2>\n"
        + figure("ilustracao-tres-pilares.jpg", "Os três pilares: Combate, Mundo e Almas."),
        1,
    )
    cap9 = (
        '<h1 class="chapter-title"><span class="chap-label">CAPÍTULO 9</span>COMBATE</h1>\n'
        + ORNAMENT
    )
    if cap9 in html:
        html = html.replace(
            cap9,
            cap9
            + "\n"
            + figure(
                "ilustracao-combate.jpg",
                "Posição, ações e combo decidem o combate.",
            ),
            1,
        )

    # Fix callout divs that may have lost inner markdown paragraphs
    return html


def md_to_html(md_text: str) -> str:
    body = clean_source(md_text)
    html_body = markdown.markdown(
        body,
        extensions=[
            "tables",
            "fenced_code",
            "sane_lists",
            "nl2br",
            "smarty",
            MarkdownInHtmlExtension(),
        ],
        extension_configs={"md_in_html": {"nested": True}},
        output_format="html5",
    )
    html_body = enhance_html(html_body)
    css = CSS_PATH.read_text(encoding="utf-8")
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<title>Sistema das Almas — Livro do Jogador</title>
<style>
{css}
</style>
</head>
<body>
{COVER_HTML}
<div class="book-frame">
{html_body}
</div>
</body>
</html>
"""


async def html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        # Wait for Google Fonts
        await page.wait_for_timeout(1200)
        await page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            prefer_css_page_size=True,
            display_header_footer=True,
            header_template="<div></div>",
            footer_template="""
              <div style="width:100%;font-size:9px;color:#6e5f4f;font-family:Georgia,serif;
                          text-align:center;padding:0 16mm;">
                <span class="pageNumber"></span>
              </div>
            """,
            margin={
                "top": "0mm",
                "bottom": "12mm",
                "left": "0mm",
                "right": "0mm",
            },
        )
        await browser.close()


def main() -> None:
    md_text = MD_PATH.read_text(encoding="utf-8")
    html = md_to_html(md_text)
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"HTML: {HTML_PATH}")
    asyncio.run(html_to_pdf(HTML_PATH, PDF_PATH))
    print(f"PDF:  {PDF_PATH} ({PDF_PATH.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
