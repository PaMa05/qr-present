#!/usr/bin/env python3
"""
Build a static website from entries.xlsx + images/, with optional QR generation (kept off-page).
Detail pages show: Photo, Date, Description.

Date source priority:
  1) Excel column "Datum/Jahr" (case-insensitive) if present
  2) Excel column "Datum"      (case-insensitive)
  3) EXIF DateTimeOriginal
  4) File modified time

Displayed date format: DD.MM.YYYY

Optional flags:
  --base-url URL          Base URL for the deployed site (required for QR contents)
  --make_qr               Generate PNG QRs (assets/qrcodes/NUM.png) linking to each detail page
  --qrs_pdf               Create overview PDF (3x5 on A4): site/qrcodes.pdf
  --labels                Create labels PDF (45x45 mm grid on A4): site/qrcodes_labels.pdf
  --cols/--rows           Grid for labels PDF (default 4x6)
  --margin-left-mm ...    Left/top margins for labels PDF
  --h-gap-mm/--v-gap-mm   Gaps between labels
  --no-entry-labels       Hide "Eintrag NNN" under each QR in PDFs

Excel columns (header not case-sensitive):
- Required:  Bildname
- Optional:  Beschreibung  (or text)
- Optional:  Datum/Jahr    (preferred) or Datum
"""

import os, shutil, re, argparse
from pathlib import Path
from typing import Optional
import pandas as pd
from PIL import Image, ExifTags, ImageDraw, ImageFont
from datetime import datetime
import qrcode

# ---------------- Config ----------------
INPUT_XLSX = "entries.xlsx"
IMAGES_DIR = "images"
OUT_DIR = "docs"
MAX_IMAGE_WIDTH = 1600
THUMB_WIDTH = 600

CSS = """
:root{--bg:#fafafa;--fg:#222;--muted:#666;--card:#fff;--shadow:rgba(0,0,0,.06);--radius:16px;--maxw:960px}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,'Helvetica Neue',Arial}
img{max-width:100%;height:auto;display:block}
a{color:#0a58ca;text-decoration:none}a:hover{text-decoration:underline}
.site-header,.site-footer{max-width:var(--maxw);margin:auto;padding:16px 20px}
.brand{font-weight:700;font-size:20px}
main{max-width:var(--maxw);margin:0 auto;padding:10px 20px 40px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:18px}
.card{background:var(--card);border-radius:var(--radius);box-shadow:0 10px 20px var(--shadow);overflow:hidden;transition:transform .15s ease,box-shadow .15s ease}
.card:hover{transform:translateY(-2px);box-shadow:0 14px 24px var(--shadow)}
.card .thumb{aspect-ratio:4/3;object-fit:cover}.card .body{padding:12px 14px}.card .meta{font-size:12px;color:var(--muted);display:flex;gap:10px;flex-wrap:wrap}
.entry-card{background:var(--card);border-radius:var(--radius);box-shadow:0 10px 20px var(--shadow);padding:18px}
.entry-figure{margin:0 0 12px 0}.entry-text{white-space:pre-wrap;font-size:18px}.entry-meta{color:var(--muted);margin:6px 0 14px 0}
.entry-nav{display:flex;gap:12px;margin-top:16px;flex-wrap:wrap}
"""

INDEX_TEMPLATE = """<!doctype html><html lang="de"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><title>Übersicht</title><style>{css}</style></head><body><header class="site-header"><div class="brand">🎁 QR‑Geschenk</div></header><main><section><h1>Alle Einträge</h1><div class="grid">{cards}</div></section></main><footer class="site-footer"><p>Erstellt mit ❤️ fürs Geschenk</p></footer></body></html>"""
CARD_TEMPLATE = """<a class="card" href="{href}"><img class="thumb" src="{thumb_src}" alt=""><div class="body"><div class="meta"><span>#{num}</span><span>{date}</span></div><div>{preview}</div></div></a>"""
ENTRY_TEMPLATE = """<!doctype html><html lang="de"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><title>Eintrag {num}</title><style>{css}</style></head><body><header class="site-header"><a href="../index.html" class="brand">🎁 QR‑Geschenk</a></header><main><article class="entry"><div class="entry-card"><figure class="entry-figure"><img src="../assets/images/{image}" alt=""></figure><div class="entry-meta">{date}</div><div class="entry-text">{text_html}</div></div><nav class="entry-nav"><a href="../index.html">← Zurück zur Übersicht</a>{prev_link}{next_link}</nav></article></main><footer class="site-footer"><p>Erstellt mit ❤️ fürs Geschenk</p></footer></body></html>"""

def ensure_dir(p: Path): p.mkdir(parents=True, exist_ok=True)

def resize_copy(src: Path, dst: Path, max_w: int):
    ensure_dir(dst.parent)
    with Image.open(src) as im:
        im = im.convert("RGB") if im.mode in ("P","RGBA","LA") else im
        if im.width > max_w:
            ratio = max_w / im.width
            im = im.resize((max_w, int(im.height * ratio)))
        im.save(dst, quality=88)

def make_thumb(src: Path, dst: Path, width: int):
    ensure_dir(dst.parent)
    with Image.open(src) as im:
        im = im.convert("RGB") if im.mode in ("P","RGBA","LA") else im
        ratio = width / im.width
        im = im.resize((width, max(1, int(im.height * ratio))))
        im.save(dst, quality=82)

EXIF_TAGS = {v:k for k,v in ExifTags.TAGS.items()}
TAG_ORIG = EXIF_TAGS.get("DateTimeOriginal", 36867)
TAG_DIGI = EXIF_TAGS.get("DateTimeDigitized", 36868)
TAG_DATE = EXIF_TAGS.get("DateTime", 306)
DATE_RE = re.compile(r"(\\d{4}):(\\d{2}):(\\d{2})[ T](\\d{2}):(\\d{2}):(\\d{2})")

def exif_datetime(path: Path):
    try:
        with Image.open(path) as im:
            exif = getattr(im, "_getexif", lambda: None)()
            if not exif: return None
            for tag in (TAG_ORIG, TAG_DIGI, TAG_DATE):
                if tag in exif:
                    raw = exif.get(tag)
                    if isinstance(raw, bytes): raw = raw.decode(errors="ignore")
                    m = DATE_RE.search(str(raw))
                    if m:
                        y,mo,d,hh,mm,ss = map(int, m.groups())
                        return datetime(y,mo,d,hh,mm,ss)
    except Exception:
        return None
    return None

def normalize_colname(name: str) -> str:
    # Lowercase, remove spaces and punctuation like '/', '_', '-'
    s = name.strip().lower()
    for ch in (" ", "\t", "/", "\\\\", "_", "-"):
        s = s.replace(ch, "")
    return s

def find_date_column(df_columns) -> Optional[str]:
    # Preferred "datum/jahr" (normalized -> "datumjahr"), then "datum"
    mapping = {normalize_colname(c): c for c in df_columns}
    if "datumjahr" in mapping: return mapping["datumjahr"]
    if "datum" in mapping: return mapping["datum"]
    return None

def safe_date_from_excel(val) -> Optional[datetime]:
    if pd.isna(val): return None
    # Handle year-only like '2004'
    s = str(val).strip()
    if re.fullmatch(r"\\d{4}", s):
        return datetime(int(s), 1, 1)
    try:
        dt = pd.to_datetime(val, dayfirst=True, errors="coerce")
        if pd.isna(dt): return None
        if isinstance(dt, pd.Timestamp): return dt.to_pydatetime()
        return dt
    except Exception:
        return None

def md_to_html(s: str) -> str:
    s = s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    s = re.sub(r"\\*\\*(.+?)\\*\\*", r"<strong>\\1</strong>", s)
    s = re.sub(r"\\*(.+?)\\*", r"<em>\\1</em>", s)
    return s

def text_size(draw: ImageDraw.ImageDraw, text: str, font=None):
    bbox = draw.textbbox((0, 0), text, font=font)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])

def make_qr_png(data, out_path, box_size=10, border=4):
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box_size, border=border)
    qr.add_data(data); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    ensure_dir(out_path.parent); img.save(out_path)

def mm_to_px(mm, dpi=300): return int(round(mm * dpi / 25.4))

def make_qr_overview_pdf(qr_dir: Path, entries_meta, out_pdf_path: Path):
    # A4, 300 dpi, 3x5 grid
    A4_W, A4_H = 2480, 3508
    cols, rows = 3, 5
    margin = 100
    cell_w = (A4_W - 2*margin) // cols
    cell_h = (A4_H - 2*margin) // rows
    pages = []
    items = [(m["num"], qr_dir / f'{m["num"]}.png') for m in entries_meta if (qr_dir / f'{m["num"]}.png').exists()]
    for i in range(0, len(items), cols*rows):
        page = Image.new("RGB", (A4_W, A4_H), "white"); dr = ImageDraw.Draw(page)
        for idx, (num, p) in enumerate(items[i:i+cols*rows]):
            r, c = divmod(idx, cols)
            x0 = margin + c*cell_w; y0 = margin + r*cell_h
            img = Image.open(p).convert("RGB")
            label_space = mm_to_px(5)
            target = min(cell_w, cell_h - label_space) - mm_to_px(3)
            target = max(10, target)
            img = img.resize((target, target))
            ox = x0 + (cell_w - target)//2; oy = y0 + (cell_h - label_space - target)//2
            page.paste(img, (ox, oy))
            text = f"Eintrag {num}"
            tw, th = text_size(dr, text)
            tx = x0 + (cell_w - tw)//2; ty = y0 + cell_h - label_space + (label_space - th)//2
            dr.text((tx, ty), text, fill=(0,0,0))
        pages.append(page)
    if not pages: pages = [Image.new("RGB", (A4_W, A4_H), "white")]
    pages[0].save(out_pdf_path, save_all=True, append_images=pages[1:])

def make_labels_pdf(qr_dir: Path, entries_meta, out_pdf_path: Path,
                    cols=4, rows=6, margin_left_mm=8, margin_top_mm=8,
                    h_gap_mm=3, v_gap_mm=3, include_labels=True):
    # A4 300 dpi, 45x45 mm labels grid by default
    page_w, page_h = 2480, 3508
    cell_w = mm_to_px(45); cell_h = mm_to_px(45)
    ml = mm_to_px(margin_left_mm); mt = mm_to_px(margin_top_mm)
    hg = mm_to_px(h_gap_mm); vg = mm_to_px(v_gap_mm)
    items = [(m["num"], qr_dir / f'{m["num"]}.png') for m in entries_meta if (qr_dir / f'{m["num"]}.png').exists()]
    pages = []; i = 0
    while i < len(items):
        page = Image.new("RGB", (page_w, page_h), "white"); dr = ImageDraw.Draw(page)
        for r in range(rows):
            for c in range(cols):
                if i >= len(items): break
                num, p = items[i]; i += 1
                x0 = ml + c * (cell_w + hg); y0 = mt + r * (cell_h + vg)
                img = Image.open(p).convert("RGB")
                label_space = mm_to_px(5) if include_labels else 0
                target = min(cell_w, cell_h - label_space) - mm_to_px(3)
                target = max(10, target)
                img = img.resize((target, target))
                ox = x0 + (cell_w - target)//2; oy = y0 + (cell_h - label_space - target)//2
                page.paste(img, (ox, oy))
                if include_labels:
                    text = f"Eintrag {num}"
                    tw, th = text_size(dr, text)
                    tx = x0 + (cell_w - tw)//2; ty = y0 + cell_h - label_space + (label_space - th)//2
                    dr.text((tx, ty), text, fill=(0,0,0))
        pages.append(page)
    if not pages: pages = [Image.new("RGB", (page_w, page_h), "white")]
    pages[0].save(out_pdf_path, save_all=True, append_images=pages[1:])

def main():
    ap = argparse.ArgumentParser(description="Build static site; optionally generate QR codes + PDFs (off-page).")
    ap.add_argument("--xlsx", default=INPUT_XLSX)
    ap.add_argument("--images", default=IMAGES_DIR)
    ap.add_argument("--out", default=OUT_DIR)
    # Optional QR pipeline
    ap.add_argument("--base-url", default=None, help="Base URL for deployed site (required for QRs)")
    ap.add_argument("--make_qr", action="store_true", help="Generate PNG QRs for each detail page")
    ap.add_argument("--qrs_pdf", action="store_true", help="Create overview PDF (A4 3x5)")
    ap.add_argument("--labels", action="store_true", help="Create labels PDF (A4, 45x45mm grid)")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=6)
    ap.add_argument("--margin-left-mm", type=float, default=8.0)
    ap.add_argument("--margin-top-mm", type=float, default=8.0)
    ap.add_argument("--h-gap-mm", type=float, default=3.0)
    ap.add_argument("--v-gap-mm", type=float, default=3.0)
    ap.add_argument("--no-entry-labels", action="store_true")
    args = ap.parse_args()

    root = Path(".")
    xlsx = root / args.xlsx
    images_dir = root / args.images
    out_dir = root / args.out

    if not xlsx.exists(): raise FileNotFoundError(f"Excel nicht gefunden: {xlsx}")
    if not images_dir.exists(): raise FileNotFoundError(f"Bilder-Ordner nicht gefunden: {images_dir}")

    if out_dir.exists(): shutil.rmtree(out_dir)
    (out_dir / "assets" / "images").mkdir(parents=True, exist_ok=True)
    (out_dir / "assets" / "thumbs").mkdir(parents=True, exist_ok=True)
    (out_dir / "e").mkdir(parents=True, exist_ok=True)

    df = pd.read_excel(xlsx)
    # Column detection (case-insensitive, tolerant to spaces/slashes)
    cols_ci = {normalize_colname(c): c for c in df.columns}
    if "bildname" not in cols_ci: raise ValueError("Excel muss die Spalte 'Bildname' enthalten.")
    col_img = cols_ci["bildname"]
    col_desc = cols_ci.get("beschreibung") or cols_ci.get("text")
    # Prefer "Datum/Jahr" then "Datum"
    col_date = find_date_column(df.columns)

    entries = []
    for idx, row in df.iterrows():
        n = idx+1; num = str(n).zfill(3)
        img_name = str(row[col_img]).strip()
        src_img = images_dir / img_name
        if not src_img.exists(): raise FileNotFoundError(f"Bild nicht gefunden: {src_img}")

        dst_img = out_dir / "assets" / "images" / img_name
        resize_copy(src_img, dst_img, MAX_IMAGE_WIDTH)
        thumb = out_dir / "assets" / "thumbs" / img_name
        make_thumb(dst_img, thumb, THUMB_WIDTH)

        desc = ""
        if col_desc:
            val = row[col_desc]; desc = "" if pd.isna(val) else str(val)

        # 1) Excel date (Datum/Jahr preferred)
        dt = None
        if col_date:
            dt = safe_date_from_excel(row[col_date])
        # 2) EXIF
        if dt is None:
            dt = exif_datetime(src_img)
        # 3) mtime
        if dt is None:
            dt = datetime.fromtimestamp(src_img.stat().st_mtime)

        date_display = dt.strftime("%d.%m.%Y")

        entries.append({"num": num, "image": img_name, "thumb": f"assets/thumbs/{img_name}",
                        "href": f"e/{num}.html", "date": date_display, "desc": desc})

    # Build detail pages
    total = len(entries)
    for i, m in enumerate(entries):
        prev_link = f' <a href="{entries[i-1]["href"]}">« Vorheriger</a>' if i>0 else ""
        next_link = f' <a href="{entries[i+1]["href"]}">Nächster »</a>' if i<total-1 else ""
        html = ENTRY_TEMPLATE.format(css=CSS, num=m["num"], image=m["image"], date=m["date"],
                                     text_html=md_to_html(m["desc"]), prev_link=prev_link, next_link=next_link)
        (out_dir / m["href"]).write_text(html, encoding="utf-8")

    # Build index
    cards = []
    for m in entries:
        preview = (m["desc"].splitlines()[0] if m["desc"] else "").strip()
        if len(preview) > 120: preview = preview[:120] + "…"
        cards.append(CARD_TEMPLATE.format(href=m["href"], thumb_src=m["thumb"], num=m["num"], date=m["date"], preview=md_to_html(preview)))
    (out_dir / "index.html").write_text(INDEX_TEMPLATE.format(css=CSS, cards="".join(cards)), encoding="utf-8")

    # Optional QR pipeline (off-page)
    if args.make_qr or args.qrs_pdf or args.labels:
        if not args.base_url:
            raise SystemExit("--base-url ist erforderlich, um QR-Codes zu erzeugen.")
        qr_dir = out_dir / "assets" / "qrcodes"; ensure_dir(qr_dir)
        for m in entries:
            url = f"{args.base_url}/{m['href']}"
            make_qr_png(url, qr_dir / f"{m['num']}.png")
        if args.qrs_pdf:
            make_qr_overview_pdf(qr_dir, entries, out_dir / "qrcodes.pdf")
        if args.labels:
            make_labels_pdf(qr_dir, entries, out_dir / "qrcodes_labels.pdf",
                            cols=args.cols, rows=args.rows,
                            margin_left_mm=args.margin_left_mm, margin_top_mm=args.margin_top_mm,
                            h_gap_mm=args.h_gap_mm, v_gap_mm=args.v_gap_mm,
                            include_labels=(not args.no_entry_labels))

    print(f"Fertig! Website in: {out_dir}")

if __name__ == "__main__":
    main()
