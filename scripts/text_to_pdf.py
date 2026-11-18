"""
Turn a plain-text job description into a clean, text-based PDF (no dependencies).

    uv run python scripts/text_to_pdf.py data/real_jds/ivp.txt            # writes data/real_jds/ivp.pdf
    uv run python scripts/text_to_pdf.py jd.txt -o out.pdf --title "IVP – Associate Solution Engineer"

Layout rules, so pasted portal text comes out readable:
* lines starting with "*", "-", "•" or "·" become bullets (wrapped with a hanging indent);
* short title-like lines without digits or end punctuation ("Key Responsibilities") become headings;
* blank lines become paragraph gaps; everything else is body text, word-wrapped.

Uses the PDF built-in Helvetica fonts with WinAnsi encoding, so the text stays selectable
and extracts cleanly (the script checks this with the app's own PDF parser afterwards).
Characters outside Windows-1252 are replaced with "?".
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PAGE_W, PAGE_H = 595, 842  # A4 in points
MARGIN = 56
BODY_SIZE, HEADING_SIZE, TITLE_SIZE = 10.5, 12.5, 16
LINE_GAP = 1.45  # line height as a multiple of font size
BULLET_INDENT = 14
# Average Helvetica glyph width as a fraction of the font size (conservative for wrapping).
AVG_CHAR = 0.52

_BULLET = re.compile(r"^\s*(?:[*\-•·▪◦]|\d+[.)])\s+")


def _wrap(text: str, size: float, width: float) -> list[str]:
    max_chars = max(int(width / (size * AVG_CHAR)), 10)
    words, lines, current = text.split(), [], ""
    for word in words:
        while len(word) > max_chars:  # a single very long token (URL)
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:max_chars])
            word = word[max_chars:]
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _is_heading(line: str) -> bool:
    words = line.split()
    return (
        0 < len(words) <= 6
        and len(line) <= 60
        and not re.search(r"\d", line)
        and not line.rstrip().endswith((".", ",", ";"))
        and sum(w[0].isupper() for w in words if w[0].isalpha()) >= max(1, len(words) // 2)
    )


def layout(text: str, title: str | None) -> list[list[tuple[str, float, float, float]]]:
    """Return pages of (text, font size, x, y); font is bold when size > BODY_SIZE."""
    pages: list[list[tuple[str, float, float, float]]] = [[]]
    y = PAGE_H - MARGIN
    usable = PAGE_W - 2 * MARGIN

    def emit(line: str, size: float, x: float, gap_before: float = 0.0) -> None:
        nonlocal y
        height = size * LINE_GAP
        if y - gap_before - height < MARGIN:
            pages.append([])
            y = PAGE_H - MARGIN
            gap_before = 0.0
        y -= gap_before + height
        pages[-1].append((line, size, x, y))

    if title:
        for part in _wrap(title, TITLE_SIZE, usable):
            emit(part, TITLE_SIZE, MARGIN)
        y -= 6

    pending_gap = 0.0
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            pending_gap = BODY_SIZE * 0.6
            continue
        bullet = _BULLET.match(line)
        if bullet:
            content = line[bullet.end():]
            for i, part in enumerate(_wrap(content, BODY_SIZE, usable - BULLET_INDENT)):
                emit(("•  " if i == 0 else "") + part, BODY_SIZE,
                     MARGIN + (0 if i == 0 else BULLET_INDENT), pending_gap if i == 0 else 0.0)
        elif _is_heading(line):
            emit(line, HEADING_SIZE, MARGIN, max(pending_gap, HEADING_SIZE * 0.7))
        else:
            for i, part in enumerate(_wrap(line, BODY_SIZE, usable)):
                emit(part, BODY_SIZE, MARGIN, pending_gap if i == 0 else 0.0)
        pending_gap = 0.0
    return pages


def _pdf_string(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def render(pages: list[list[tuple[str, float, float, float]]], doc_title: str) -> bytes:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # filled in once the page tree exists
    page_tree = add(b"")
    regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    page_ids = []
    for lines in pages:
        ops = []
        for text, size, x, y in lines:
            font = b"/F2" if size > BODY_SIZE else b"/F1"
            ops.append(b"BT %s %.1f Tf %.2f %.2f Td %s Tj ET" % (font, size, x, y, _pdf_string(text)))
        stream = b"\n".join(ops)
        content = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        page_ids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>"
            % (page_tree, PAGE_W, PAGE_H, content, regular, bold)
        ))

    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
    objects[page_tree - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % page_tree
    # Metadata strings use PDFDocEncoding, not WinAnsi; UTF-16BE with a BOM is unambiguous.
    title_hex = ("﻿" + doc_title).encode("utf-16-be").hex().upper().encode()
    info = add(b"<< /Title <%s> /Producer (placement-agent text_to_pdf) >>" % title_hex)

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, catalog, info, xref)
    return bytes(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a plain-text JD into a text-based PDF.")
    parser.add_argument("source", type=Path, help="UTF-8 .txt file")
    parser.add_argument("-o", "--output", type=Path, help="default: same name with .pdf")
    parser.add_argument("--title", help="optional title printed at the top")
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8-sig")
    output = args.output or args.source.with_suffix(".pdf")
    pdf = render(layout(text, args.title), args.title or args.source.stem)
    output.write_bytes(pdf)

    # Round-trip through the app's own parser: what gets uploaded is what the app will read.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.services.pdf import text_from_upload

    extracted = text_from_upload(output.name, pdf)
    source_words = set(re.findall(r"[a-z0-9]+", text.lower()))
    extracted_words = set(re.findall(r"[a-z0-9]+", extracted.lower()))
    missing = sorted(source_words - extracted_words)
    pages = pdf.count(b"/Type /Page ")
    print(f"wrote {output} ({len(pdf) // 1024 + 1} KB, {pages} page{'s' if pages != 1 else ''})")
    print(f"round-trip: {len(source_words) - len(missing)}/{len(source_words)} distinct words extracted"
          + (f"; missing: {', '.join(missing[:10])}" if missing else ""))
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
