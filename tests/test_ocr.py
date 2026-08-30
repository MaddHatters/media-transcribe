"""Tests for OCR wrapper — mock RapidOCR."""
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys


def test_ocr_image_mocked(tmp_path):
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    mock_image_mod = MagicMock()
    mock_np = MagicMock()
    mock_image_mod.open.return_value = MagicMock()
    mock_np.array.return_value = MagicMock()

    with patch("src.analyze.ocr._get_engine") as mock_engine, \
         patch.dict(sys.modules, {"PIL": MagicMock(), "PIL.Image": mock_image_mod, "numpy": mock_np}):
        mock_engine.return_value = MagicMock(
            return_value=([[None, "Hello World", None]], None)
        )
        from src.analyze.ocr import ocr_image
        text = ocr_image(img)
        assert "Hello World" in text


def test_ocr_frames_mocked(tmp_path):
    for i in range(3):
        (tmp_path / f"frame_{i}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    mock_image_mod = MagicMock()
    mock_np = MagicMock()
    mock_image_mod.open.return_value = MagicMock()
    mock_np.array.return_value = MagicMock()

    with patch("src.analyze.ocr._get_engine") as mock_engine, \
         patch.dict(sys.modules, {"PIL": MagicMock(), "PIL.Image": mock_image_mod, "numpy": mock_np}):
        mock_engine.return_value = MagicMock(
            return_value=([[None, "Text", None]], None)
        )
        from src.analyze.ocr import ocr_frames
        results = ocr_frames(tmp_path)
        assert len(results) == 3
