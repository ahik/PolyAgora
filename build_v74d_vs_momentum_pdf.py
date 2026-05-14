"""
Render V74d_vs_Momentum.md to a PDF with a "Confidential & Proprietary"
per-page footer. Same CSS stack as build_algo_v74_pdf.py but image-aware.
"""

from __future__ import annotations

from pathlib import Path

import markdown
from weasyprint import CSS, HTML


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "V74d_vs_Momentum.md"
DST = ROOT / "V74d_vs_Momentum.pdf"


CSS_STYLE = """
@page {
    size: A4;
    margin: 22mm 18mm 22mm 18mm;

    @bottom-left {
        content: "Confidential & Proprietary";
        font-family: "DejaVu Sans", "Helvetica", sans-serif;
        font-size: 7.5pt;
        color: #777;
    }
    @bottom-center {
        content: "V7.4d vs Momentum 12-1 — When Each Wins";
        font-family: "DejaVu Sans", "Helvetica", sans-serif;
        font-size: 7.5pt;
        color: #777;
    }
    @bottom-right {
        content: "Page " counter(page) " of " counter(pages);
        font-family: "DejaVu Sans", "Helvetica", sans-serif;
        font-size: 7.5pt;
        color: #777;
    }
}

html {
    font-family: "DejaVu Sans", "Helvetica", sans-serif;
    font-size: 9.5pt;
    line-height: 1.45;
    color: #222;
}

h1 { font-size: 18pt; margin-top: 1.0em; margin-bottom: 0.4em; color: #111; border-bottom: 1px solid #ccc; padding-bottom: 0.2em; }
h2 { font-size: 14pt; margin-top: 1.0em; margin-bottom: 0.3em; color: #111; }
h3 { font-size: 11.5pt; margin-top: 0.8em; margin-bottom: 0.25em; color: #222; }
h4 { font-size: 10.5pt; margin-top: 0.6em; margin-bottom: 0.2em; color: #333; }

p { margin: 0.35em 0; text-align: justify; }
ul, ol { margin: 0.3em 0 0.3em 1.2em; padding-left: 0.4em; }
li { margin: 0.15em 0; }

blockquote {
    border-left: 3px solid #0f766e;
    padding: 0.4em 0.9em;
    margin: 0.6em 0;
    background: #ecfdf5;
    color: #333;
    font-size: 9pt;
}
blockquote p { margin: 0.2em 0; }

code {
    font-family: "DejaVu Sans Mono", "Courier New", monospace;
    font-size: 8.5pt;
    background: #f3f3f3;
    padding: 0 3px;
    border-radius: 2px;
    color: #0f766e;
}
pre {
    background: #f6f6f6;
    border: 1px solid #e4e4e4;
    border-radius: 3px;
    padding: 8px 10px;
    font-size: 8pt;
    line-height: 1.35;
    overflow-x: auto;
    page-break-inside: avoid;
}
pre code { background: transparent; color: #222; padding: 0; }

table {
    border-collapse: collapse;
    margin: 0.6em 0;
    font-size: 8.5pt;
    width: 100%;
    page-break-inside: avoid;
}
th, td {
    border: 1px solid #d4d4d4;
    padding: 4px 7px;
    text-align: left;
    vertical-align: top;
}
th { background: #f1f1f1; font-weight: 600; }

img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 0.6em auto;
    page-break-inside: avoid;
}

small { font-size: 7.5pt; color: #777; }

hr { border: 0; border-top: 1px solid #ccc; margin: 1.2em 0; }

a { color: #1f5fab; text-decoration: none; }

h1, h2, h3, h4 { page-break-after: avoid; }
li, tr { page-break-inside: avoid; }
"""


def main() -> None:
    md_text = SRC.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "codehilite", "sane_lists"],
        extension_configs={
            "codehilite": {"guess_lang": False, "noclasses": True, "pygments_style": "default"},
        },
    )
    html_doc = f"""<!doctype html>
<html><head><meta charset=\"utf-8\"><title>V7.4d vs Momentum 12-1</title></head>
<body>{html_body}</body></html>"""

    HTML(string=html_doc, base_url=str(ROOT)).write_pdf(
        str(DST), stylesheets=[CSS(string=CSS_STYLE)]
    )
    print(f"[ok] wrote {DST} ({DST.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
