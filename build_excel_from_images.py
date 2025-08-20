#!/usr/bin/env python3
"""
Build an Excel (entries.xlsx) with columns:
ID;Bildernamen;Datum/Jahr;Beschreibung;Link

- Scans images in a folder
- Sorts by date parsed from filename if possible (YYYY-MM-DD_HHMMSS)
- Otherwise falls back to EXIF DateTimeOriginal, mdls (macOS), birthtime, mtime
- Assigns sequential IDs (zero-padded to fit total), starting at 001
- Optional: fill Beschreibung from file name (--desc-from-name)
- Optional: set --base-url to prefill Link as {base_url}/e/{ID}.html
- Supports --recursive to include subfolders
"""
import argparse, sys, re, platform, subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple
import pandas as pd

try:
    from PIL import Image, ExifTags
except ImportError:
    print("This script requires Pillow. Install with: pip install Pillow", file=sys.stderr)
    sys.exit(1)

try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except Exception:
    pass

IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".heif"}
EXIF_TAGS = {v: k for k, v in ExifTags.TAGS.items()}
TAG_DATETIME_ORIGINAL = EXIF_TAGS.get("DateTimeOriginal", 36867)
TAG_DATETIME_DIGITIZED = EXIF_TAGS.get("DateTimeDigitized", 36868)
TAG_DATETIME = EXIF_TAGS.get("DateTime", 306)
DATE_RE_EXIF = re.compile(r"(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})")
DATE_RE_FILENAME = re.compile(r"(\d{4})-(\d{2})-(\d{2})[_\-](\d{2})(\d{2})(\d{2})")

def parse_args():
    ap = argparse.ArgumentParser(description="Generate Excel with ID;Bildernamen;Datum/Jahr;Beschreibung;Link from images")
    ap.add_argument("--dir", required=True, help="Folder with images")
    ap.add_argument("--recursive", action="store_true", help="Include subfolders")
    ap.add_argument("--write", action="store_true", help="Actually write Excel (otherwise preview only)")
    ap.add_argument("--out", default=None, help="Output .xlsx path (default: entries.xlsx in --dir)")
    ap.add_argument("--base-url", default=None, help="If set, fills Link column as {base-url}/e/{ID}.html")
    ap.add_argument("--desc-from-name", action="store_true", help="Fill Beschreibung from filename (without extension)")
    return ap.parse_args()

def iter_images(root: Path, recursive: bool):
    if recursive:
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in IMG_EXTS:
                yield p
    else:
        for p in root.iterdir():
            if p.is_file() and p.suffix.lower() in IMG_EXTS:
                yield p

def datetime_from_filename(p: Path) -> Optional[datetime]:
    m = DATE_RE_FILENAME.search(p.stem)
    if m:
        y, mo, d, hh, mm, ss = map(int, m.groups())
        return datetime(y, mo, d, hh, mm, ss)
    return None

def extract_exif_datetime(img_path: Path) -> Optional[datetime]:
    try:
        with Image.open(img_path) as im:
            exif = getattr(im, "_getexif", lambda: None)()
            if not exif:
                return None
            for tag_id in (TAG_DATETIME_ORIGINAL, TAG_DATETIME_DIGITIZED, TAG_DATETIME):
                if tag_id in exif:
                    raw = exif.get(tag_id)
                    if isinstance(raw, bytes):
                        raw = raw.decode(errors="ignore")
                    if not raw:
                        continue
                    m = DATE_RE_EXIF.search(str(raw))
                    if m:
                        y, mo, d, hh, mm, ss = map(int, m.groups())
                        return datetime(y, mo, d, hh, mm, ss)
    except Exception:
        return None
    return None

def mdls_creation_datetime(p: Path) -> Optional[datetime]:
    if platform.system() != "Darwin":
        return None
    try:
        out = subprocess.check_output(
            ["mdls", "-raw", "-name", "kMDItemContentCreationDate", str(p)],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        if out and out != "(null)":
            parts = out.split()
            if len(parts) >= 2:
                dt_str = " ".join(parts[:2])
                return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    return None

def fs_birth_or_mtime(p: Path) -> datetime:
    try:
        bt = getattr(p.stat(), "st_birthtime", None)
    except Exception:
        bt = None
    if bt:
        return datetime.fromtimestamp(bt)
    return datetime.fromtimestamp(p.stat().st_mtime)

def nice_desc_from_name(name: str) -> str:
    base = Path(name).stem
    base = re.sub(r"[_\-]+", " ", base).strip()
    return base[:1].upper() + base[1:] if base else ""

def main():
    args = parse_args()
    root = Path(args.dir).expanduser().resolve()
    assert root.exists() and root.is_dir(), f"Folder not found: {root}"

    items: List[Tuple[Path, datetime]] = []
    for p in iter_images(root, args.recursive):
        dt = datetime_from_filename(p) or extract_exif_datetime(p) or mdls_creation_datetime(p) or fs_birth_or_mtime(p)
        items.append((p, dt))

    if not items:
        print("No images found.")
        return

    items.sort(key=lambda x: x[1])
    pad = max(3, len(str(len(items))))

    rows = []
    for i, (p, dt) in enumerate(items, start=1):
        id_str = str(i).zfill(pad)
        bildname = p.name
        datum = dt.strftime("%Y-%m-%d %H:%M:%S")
        beschreibung = nice_desc_from_name(bildname) if args.desc_from_name else ""
        link = f"{args.base_url}/e/{id_str}.html" if args.base_url else ""
        rows.append((id_str, bildname, datum, beschreibung, link))

    df = pd.DataFrame(rows, columns=["ID","Bildernamen","Datum/Jahr","Beschreibung","Link"])

    if not args.write:
        print(df.head(min(10, len(df))))
        print(f"\nTotal rows: {len(df)} (ID width={pad} digits). Use --write to save Excel.")
        return

    out_path = Path(args.out) if args.out else (root / "entries.xlsx")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_path, index=False)
    print(f"Wrote Excel: {out_path}")

if __name__ == "__main__":
    main()
