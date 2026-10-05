"""Versioned pixel transform shared by training and LocalONNXBackend."""
from __future__ import annotations

import numpy as np
from PIL import Image

PREPROCESSING_VERSION = "monochrome-v1"


def dicom_tensor(ds, input_size: tuple[int, int] | list[int]) -> np.ndarray:
    """Return float32 NCHW tensor; reject constant or nonfinite input."""
    pixels = ds.pixel_array.astype(np.float32)
    if pixels.ndim != 2 or not np.all(np.isfinite(pixels)):
        raise ValueError("Expected one finite monochrome image")
    dynamic_range = float(np.max(pixels) - np.min(pixels))
    if dynamic_range <= 0:
        raise ValueError("Constant intensity image")
    pixels = (pixels - np.min(pixels)) / dynamic_range
    if ds.PhotometricInterpretation == "MONOCHROME1":
        pixels = 1 - pixels
    elif ds.PhotometricInterpretation != "MONOCHROME2":
        raise ValueError("Unsupported photometric interpretation")
    height, width = input_size
    image = Image.fromarray(np.uint8(np.rint(pixels * 255))).resize((width, height), Image.Resampling.BILINEAR)
    return np.asarray(image, dtype=np.float32)[None, None] / 255.0
