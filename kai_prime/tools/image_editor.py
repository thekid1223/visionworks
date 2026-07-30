"""Image Editor — Pillow-based image editing operations."""
from __future__ import annotations

import os
import time
from pathlib import Path

try:
    from PIL import Image, ImageEnhance, ImageFilter as PILFilter, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


_UPLOADS = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kai_prime_data", "uploads"))


def _edit_path(original: str, suffix: str) -> str:
    stem, ext = Path(original).stem, Path(original).suffix or ".jpg"
    name = f"{stem}_{suffix}{ext}"
    dst = _UPLOADS / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        name = f"{stem}_{suffix}_{int(time.time())}{ext}"
        dst = _UPLOADS / name
    return str(dst)


class ImageEditor:

    def __init__(self, uploads_dir: str | Path | None = None):
        self.uploads = Path(uploads_dir) if uploads_dir else _UPLOADS
        self.uploads.mkdir(parents=True, exist_ok=True)

    def _load(self, path: str) -> Image.Image:
        p = Path(path)
        if not p.is_absolute():
            p = self.uploads / p.name
        return Image.open(str(p))

    def _save(self, img: Image.Image, dst: str) -> str:
        fmt = Path(dst).suffix.lstrip(".").upper()
        if fmt == "JPG":
            fmt = "JPEG"
        if fmt == "JPEG" and img.mode == "RGBA":
            img = img.convert("RGB")
        img.save(dst, quality=92)
        return str(Path(dst).name)

    def resize(self, path: str, width: int, height: int) -> dict:
        img = self._load(path)
        img2 = img.resize((width, height), Image.LANCZOS)
        dst = _edit_path(path, f"resize_{width}x{height}")
        return {"url": self._save(img2, dst), "width": width, "height": height}

    def crop(self, path: str, x: int, y: int, w: int, h: int) -> dict:
        img = self._load(path)
        img2 = img.crop((x, y, x + w, y + h))
        dst = _edit_path(path, f"crop_{w}x{h}")
        return {"url": self._save(img2, dst), "width": img2.width, "height": img2.height}

    def rotate(self, path: str, degrees: float) -> dict:
        img = self._load(path)
        img2 = img.rotate(degrees, expand=True, resample=Image.BICUBIC)
        dst = _edit_path(path, f"rot_{int(degrees)}")
        return {"url": self._save(img2, dst)}

    def apply_filter(self, path: str, filter_type: str) -> dict:
        img = self._load(path)
        fmap = {
            "grayscale": lambda i: i.convert("L").convert("RGB"),
            "sepia": self._sepia,
            "blur": lambda i: i.filter(PILFilter.BLUR),
            "sharpen": lambda i: i.filter(PILFilter.SHARPEN),
            "edge": lambda i: i.filter(PILFilter.FIND_EDGES).convert("RGB"),
            "emboss": lambda i: i.filter(PILFilter.EMBOSS),
            "smooth": lambda i: i.filter(PILFilter.SMOOTH),
        }
        fn = fmap.get(filter_type)
        if not fn:
            raise ValueError(f"Unknown filter: {filter_type}")
        img2 = fn(img)
        dst = _edit_path(path, filter_type)
        return {"url": self._save(img2, dst)}

    @staticmethod
    def _sepia(img: Image.Image) -> Image.Image:
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        px = img.load()
        for y in range(h):
            for x in range(w):
                r, g, b = px[x, y]
                tr = int(0.393 * r + 0.769 * g + 0.189 * b)
                tg = int(0.349 * r + 0.686 * g + 0.168 * b)
                tb = int(0.272 * r + 0.534 * g + 0.131 * b)
                px[x, y] = (min(tr, 255), min(tg, 255), min(tb, 255))
        return img

    def adjust(self, path: str, brightness: float = 1.0, contrast: float = 1.0) -> dict:
        img = self._load(path)
        if brightness != 1.0:
            img = ImageEnhance.Brightness(img).enhance(brightness)
        if contrast != 1.0:
            img = ImageEnhance.Contrast(img).enhance(contrast)
        dst = _edit_path(path, f"adj_b{int(brightness*100)}_c{int(contrast*100)}")
        return {"url": self._save(img, dst)}

    def overlay_text(self, path: str, text: str, x: int = 0, y: int = 0,
                     font_size: int = 32, color: str = "white") -> dict:
        img = self._load(path).convert("RGBA")
        txt = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(txt)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()
        draw.text((x, y), text, fill=color, font=font)
        img2 = Image.alpha_composite(img, txt).convert("RGB")
        dst = _edit_path(path, "text")
        return {"url": self._save(img2, dst)}

    def info(self, path: str) -> dict:
        img = self._load(path)
        return {
            "width": img.width,
            "height": img.height,
            "format": img.format or "unknown",
            "mode": img.mode,
            "size_kb": round(Path(self._resolve(path)).stat().st_size / 1024, 1),
        }

    def _resolve(self, path: str) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = self.uploads / p.name
        return str(p)


TOOLS = {
    "edit_image_resize": {"description": "Resize image. Args: path, width, height", "handler": None},
    "edit_image_crop": {"description": "Crop image. Args: path, x, y, w, h", "handler": None},
    "edit_image_rotate": {"description": "Rotate image. Args: path, degrees", "handler": None},
    "edit_image_filter": {"description": "Apply filter. Args: path, filter_type (grayscale/sepia/blur/sharpen/edge/emboss/smooth)", "handler": None},
    "edit_image_adjust": {"description": "Adjust brightness/contrast. Args: path, brightness, contrast", "handler": None},
    "edit_image_text": {"description": "Overlay text. Args: path, text, x, y, font_size, color", "handler": None},
    "edit_image_info": {"description": "Get image info. Args: path", "handler": None},
}
