"""OCR wrapper — lazy RapidOCR for frame text extraction."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_ENGINE = None


def _get_engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


def ocr_image(image_path: Path) -> str:
    """Run OCR on a single image file. Returns extracted text."""
    import numpy as np
    from PIL import Image

    engine = _get_engine()
    img = np.array(Image.open(image_path))
    result, _ = engine(img)
    if not result:
        return ""
    return "\n".join(line[1] for line in result)


def ocr_frames(frames_dir: Path) -> dict[str, str]:
    """Run OCR on all image files in a directory. Returns {filename: text}."""
    results: dict[str, str] = {}
    image_exts = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
    for img_path in sorted(frames_dir.iterdir()):
        if img_path.suffix.lower() in image_exts:
            text = ocr_image(img_path)
            results[img_path.name] = text
    return results
