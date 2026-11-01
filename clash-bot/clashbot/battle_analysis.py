from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .geometry import Point


@dataclass(frozen=True)
class FriendlyCluster:
    center: Point
    pixels: int
    bounds: tuple[int, int, int, int]


def find_friendly_air_cluster(
    image_path: str | Path,
    screen: tuple[int, int],
    profile: dict[str, Any],
    *,
    min_pixels: int = 180,
) -> FriendlyCluster | None:
    image = Image.open(image_path).convert("RGB")
    if image.size != screen:
        image = image.resize(screen)

    pixels = np.asarray(image)
    mask = _friendly_air_mask(pixels)
    _keep_playfield(mask, profile, screen)

    clusters = [cluster for cluster in _clusters(mask) if cluster.pixels >= min_pixels]
    if not clusters:
        return None
    return max(clusters, key=lambda cluster: cluster.pixels)


def _friendly_air_mask(pixels: np.ndarray) -> np.ndarray:
    red = pixels[:, :, 0].astype(np.int16)
    green = pixels[:, :, 1].astype(np.int16)
    blue = pixels[:, :, 2].astype(np.int16)
    maximum = np.maximum.reduce([red, green, blue])
    minimum = np.minimum.reduce([red, green, blue])
    saturation = maximum - minimum

    cyan = (blue > 155) & (green > 105) & (red < 165) & ((blue - red) > 45) & (saturation > 60)
    electric_blue = (blue > 145) & (green > 135) & (red < 190) & ((blue - red) > 35) & (saturation > 50)
    violet = (blue > 140) & (red > 105) & (green < 130) & ((blue - green) > 35) & (saturation > 55)
    return cyan | electric_blue | violet


def _keep_playfield(mask: np.ndarray, profile: dict[str, Any], screen: tuple[int, int]) -> None:
    width, height = screen
    deployment = profile.get("deployment", {})
    if not isinstance(deployment, dict):
        deployment = {}
    bounds = deployment.get("safe_bounds", {})
    if not isinstance(bounds, dict):
        bounds = {}

    left = int(bounds.get("left", round(width * 0.06)))
    top = int(bounds.get("top", round(height * 0.08)))
    right = int(bounds.get("right", round(width * 0.95)))
    bottom = int(bounds.get("bottom", round(height * 0.80)))

    mask[:top, :] = False
    mask[bottom:, :] = False
    mask[:, :left] = False
    mask[:, right:] = False


def _clusters(mask: np.ndarray, *, cell_size: int = 20, min_cell_pixels: int = 8) -> list[FriendlyCluster]:
    height, width = mask.shape
    grid_h = (height + cell_size - 1) // cell_size
    grid_w = (width + cell_size - 1) // cell_size
    active = np.zeros((grid_h, grid_w), dtype=bool)

    for gy in range(grid_h):
        y1 = gy * cell_size
        y2 = min(y1 + cell_size, height)
        for gx in range(grid_w):
            x1 = gx * cell_size
            x2 = min(x1 + cell_size, width)
            active[gy, gx] = int(mask[y1:y2, x1:x2].sum()) >= min_cell_pixels

    seen = np.zeros_like(active)
    clusters: list[FriendlyCluster] = []
    for gy in range(grid_h):
        for gx in range(grid_w):
            if seen[gy, gx] or not active[gy, gx]:
                continue
            cells = _walk_component(active, seen, gx, gy)
            points: list[np.ndarray] = []
            for cell_x, cell_y in cells:
                x1 = cell_x * cell_size
                y1 = cell_y * cell_size
                crop = mask[y1 : min(y1 + cell_size, height), x1 : min(x1 + cell_size, width)]
                ys, xs = np.where(crop)
                if len(xs):
                    points.append(np.stack([xs + x1, ys + y1], axis=1))
            if not points:
                continue
            coords = np.concatenate(points)
            clusters.append(
                FriendlyCluster(
                    center=(round(float(coords[:, 0].mean())), round(float(coords[:, 1].mean()))),
                    pixels=int(len(coords)),
                    bounds=(
                        int(coords[:, 0].min()),
                        int(coords[:, 1].min()),
                        int(coords[:, 0].max()),
                        int(coords[:, 1].max()),
                    ),
                )
            )
    return clusters


def _walk_component(active: np.ndarray, seen: np.ndarray, start_x: int, start_y: int) -> list[tuple[int, int]]:
    height, width = active.shape
    stack = [(start_x, start_y)]
    seen[start_y, start_x] = True
    cells: list[tuple[int, int]] = []
    while stack:
        x, y = stack.pop()
        cells.append((x, y))
        for ny in range(max(0, y - 1), min(height, y + 2)):
            for nx in range(max(0, x - 1), min(width, x + 2)):
                if seen[ny, nx] or not active[ny, nx]:
                    continue
                seen[ny, nx] = True
                stack.append((nx, ny))
    return cells
