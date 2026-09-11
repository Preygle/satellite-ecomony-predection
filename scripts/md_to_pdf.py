"""Convert a project Markdown document to a print-ready PDF.

    python scripts/md_to_pdf.py docs/REVIEW2_DOCUMENTATION.md

Renders the Markdown to styled HTML, then prints it with headless Chrome.
Chrome is used because it is already installed on this machine and handles
page breaks, table splitting and fonts correctly without a LaTeX toolchain.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Calibri, Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.55; color: #16191d; margin: 0; }

h1 { font-size: 19pt; color: #10305c; margin: 0 0 10px; padding-bottom: 7px;
     border-bottom: 2.5px solid #2f6fb8; page-break-before: always;
     page-break-after: avoid; }
h1:first-of-type { page-break-before: avoid; }
h2 { font-size: 14pt; color: #1b4b86; margin: 20px 0 8px; page-break-after: avoid; }
h3 { font-size: 11.5pt; color: #2f6fb8; margin: 15px 0 6px; page-break-after: avoid; }

p { margin: 0 0 9px; text-align: justify; }
ul, ol { margin: 0 0 10px; padding-left: 20px; }
li { margin-bottom: 4px; }

table { border-collapse: collapse; width: 100%; margin: 10px 0 14px;
        font-size: 9pt; page-break-inside: avoid; }
th { background: #eef3f9; color: #10305c; text-align: left; font-weight: 600;
     padding: 6px 8px; border: 1px solid #c5d3e3; }
td { padding: 5px 8px; border: 1px solid #d8e0ea; vertical-align: top; }
tr:nth-child(even) td { background: #fafbfd; }

code { background: #f2f4f7; border: 1px solid #dfe3e8; border-radius: 3px;
       padding: 1px 4px; font-family: Consolas, "Courier New", monospace;
       font-size: 8.8pt; color: #b3306b; }
pre { background: #f7f9fb; border: 1px solid #dfe5ec; border-left: 3px solid #2f6fb8;
      border-radius: 4px; padding: 10px 12px; overflow-x: auto;
      page-break-inside: avoid; margin: 10px 0 14px; }
pre code { background: none; border: 0; padding: 0; color: #16191d;
           font-size: 8.5pt; line-height: 1.4; }

blockquote { border-left: 3px solid #eda100; background: #fffaf0;
             margin: 12px 0; padding: 9px 14px; page-break-inside: avoid; }
blockquote p { margin: 0; }

hr { border: 0; border-top: 1px solid #dde3ea; margin: 18px 0; }
img { max-width: 100%; height: auto; display: block; margin: 10px auto 14px;
      page-break-inside: avoid; }
strong { color: #0b1befff; color: #0d2340; }
a { color: #1b4b86; text-decoration: none; }

.cover { page-break-after: always; padding-top: 55mm; text-align: center; }
.cover .t { font-size: 25pt; font-weight: 700; color: #10305c; line-height: 1.25; }
.cover .s { font-size: 13pt; color: #2f6fb8; margin-top: 12px; }
.cover .m { font-size: 11pt; color: #52596b; margin-top: 34px; line-height: 1.9; }
.cover .r { margin-top: 42px; font-size: 10pt; color: #7b8494; }
"""

COVER = """
<div class="cover">
  <div class="t">Satellite-Based Urban Growth<br>and Economic Activity<br>Intelligence System</div>
  <div class="s">Review 2 — Project Documentation</div>
  <div class="m">
    <b>BCSE497J Project I</b><br>
    School of Computer Science and Engineering<br>
    Fall Semester 2026&ndash;27<br><br>
    Study area &mdash; Varanasi, Uttar Pradesh, India
  </div>
  <div class="r">
    Team &mdash; [Name 1], [Name 2], [Name 3]<br>
    Guide &mdash; [Guide Name]
  </div>
</div>
"""


def find_browser() -> str | None:
    for b in BROWSERS:
        if Path(b).exists():
            return b
    return None


def convert(md_path: Path, pdf_path: Path, cover: bool = True) -> Path:
    text = md_path.read_text(encoding="utf-8")

    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"],
    )
    html = (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{md_path.stem}</title><style>{CSS}</style></head><body>"
            f"{COVER if cover else ''}{body}</body></html>")

    tmp_html = pdf_path.with_suffix(".build.html")
    tmp_html.write_text(html, encoding="utf-8")

    browser = find_browser()
    if browser is None:
        raise RuntimeError("No Chrome or Edge found to print the PDF.")

    cmd = [
        browser, "--headless", "--disable-gpu", "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        tmp_html.resolve().as_uri(),
    ]
    subprocess.run(cmd, capture_output=True, timeout=300)

    # Chrome writes asynchronously; wait for the file to settle.
    for _ in range(40):
        if pdf_path.exists() and pdf_path.stat().st_size > 20_000:
            break
        time.sleep(0.5)

    tmp_html.unlink(missing_ok=True)
    if not pdf_path.exists():
        raise RuntimeError(f"Chrome did not produce {pdf_path}")
    return pdf_path


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    md = Path(sys.argv[1])
    if not md.is_absolute():
        md = ROOT / md
    if not md.exists():
        print(f"not found: {md}")
        return 2
    pdf = md.with_suffix(".pdf")
    convert(md, pdf)
    print(f"wrote {pdf}  ({pdf.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
