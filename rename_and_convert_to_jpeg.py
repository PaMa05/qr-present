#!/usr/bin/env python3
"""
Rename and unify images to 'YYYY-MM-DD_HHMMSS.jpeg'.
- Converts all images (jpg, png, webp, tiff, heic, ...) to JPEG.
- Base name from EXIF DateTimeOriginal, fallback to file mtime.
- Dry-run by default, use --apply to actually rename/convert.
- Avoids overwriting by appending -1, -2, ...
"""

import argparse
import os
import sys
import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

try:
    from PIL import Image, ExifTags
except ImportError:
    print("This script requires Pillow. Install with: pip install Pillow", file=sys.stderr)
    sys.exit(1)

# Optional HEIC/HEIF support
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

DATE_RE = re.compile(r"(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})")

def parse_args():
    ap = argparse.ArgumentParser(description="Rename and unify images to JPEG with YYYY-MM-DD_HHMMSS.jpeg")
    ap.add_argument("--dir", required=True, help="Folder with images")
    ap.add_argument("--recursive", action="store_true", help="Process subfolders recursively")
    ap.add_argument("--apply", action="store_true", help="Actually rename/convert files (default: dry-run)")
    ap.add_argument("--quality", type=int, default=95, help="JPEG quality (default: 95)")
    return ap.parse_args()

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
                    m = DATE_RE.search(str(raw))
                    if m:
                        y, mo, d, hh, mm, ss = map(int, m.groups())
                        return datetime(y, mo, d, hh, mm, ss)
    except Exception:
        return None
    return None

def get_file_mtime(img_path: Path) -> datetime:
    ts = img_path.stat().st_mtime
    return datetime.fromtimestamp(ts)

def unique_target_name(target: Path) -> Path:
    if not target.exists():
        return target
    stem, ext = target.stem, target.suffix
    i = 1
    while True:
        cand = target.with_name(f"{stem}-{i}{ext}")
        if not cand.exists():
            return cand
        i += 1

def iter_images(root: Path, recursive: bool):
    if recursive:
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in IMG_EXTS:
                yield p
    else:
        for p in root.iterdir():
            if p.is_file() and p.suffix.lower() in IMG_EXTS:
                yield p

def main():
    args = parse_args()
    root = Path(args.dir).expanduser().resolve()
    assert root.exists() and root.is_dir(), f"Folder not found: {root}"

    plans = []  # (src, dst, dt, used_exif)

    for img in iter_images(root, args.recursive):
        dt = extract_exif_datetime(img)
        used_exif = True
        if dt is None:
            dt = get_file_mtime(img)
            used_exif = False
        base = dt.strftime("%Y-%m-%d_%H%M%S")
        dst = img.with_name(base + ".jpeg")
        dst = unique_target_name(dst)
        plans.append((img, dst, dt, used_exif))

    exif_count = sum(1 for _, _, _, used in plans if used)
    total = len(plans)
    print(f"Found {total} image(s). EXIF date used for {exif_count}; fallback for {total - exif_count}.")
    for src, dst, dt, used in plans:
        flag = "EXIF " if used else "mtime"
        print(f"[{flag}] {src.name}  ->  {dst.name}  (date={dt.strftime('%Y-%m-%d %H:%M:%S')})")

    if not args.apply:
        print("\nDry-run only. Add --apply to perform renaming and conversion.")
        return

    converted = 0
    for src, dst, _, _ in plans:
        try:
            with Image.open(src) as im:
                rgb = im.convert("RGB")  # ensure JPEG-compatible
                rgb.save(dst, "JPEG", quality=args.quality)
            converted += 1
            if src != dst:
                os.remove(src)
        except Exception as e:
            print(f"ERROR converting {src}: {e}")
    print(f"Converted {converted} file(s) to JPEG.")

if __name__ == "__main__":
    main()
