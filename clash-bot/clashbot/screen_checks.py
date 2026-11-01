from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def troop_bar_visible(image_path: str | Path, screen: tuple[int, int]) -> bool:
    image = Image.open(image_path).convert("RGB")
    if image.size != screen:
        image = image.resize(screen)

    pixels = np.asarray(image)
    height, width = pixels.shape[:2]
    end_button = pixels[round(height * 0.70) : round(height * 0.84), : round(width * 0.15)]
    end_red = _red_button_ratio(end_button)
    if end_red < 0.12:
        return False

    crop = pixels[round(height * 0.80) : round(height * 0.99), round(width * 0.12) : round(width * 0.98)]
    if crop.size == 0:
        return False

    red = crop[:, :, 0].astype(np.int16)
    green = crop[:, :, 1].astype(np.int16)
    blue = crop[:, :, 2].astype(np.int16)
    saturation = np.max(crop, axis=2).astype(np.int16) - np.min(crop, axis=2).astype(np.int16)

    blue_cards = (blue > 120) & (green > 80) & (red < 140) & (saturation > 50)
    purple_cards = (blue > 100) & (red > 80) & (green < 120) & (saturation > 45)
    grey_cards = (np.max(crop, axis=2) > 70) & (np.max(crop, axis=2) < 190) & (saturation < 55)
    troop_card_ratio = float(np.count_nonzero(blue_cards | purple_cards | grey_cards)) / float(crop.shape[0] * crop.shape[1])
    return troop_card_ratio > 0.03


def _red_button_ratio(pixels: np.ndarray) -> float:
    if pixels.size == 0:
        return 0.0
    red = pixels[:, :, 0].astype(np.int16)
    green = pixels[:, :, 1].astype(np.int16)
    blue = pixels[:, :, 2].astype(np.int16)
    mask = (red > 150) & (green < 120) & (blue < 120) & ((red - green) > 50) & ((red - blue) > 50)
    return float(np.count_nonzero(mask)) / float(mask.shape[0] * mask.shape[1])
