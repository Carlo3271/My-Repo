from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .geometry import Point, resolve_point


class PerimeterDetectionError(RuntimeError):
    pass


EDGE_ANCHORS = (
    "deploy_top_edge_left",
    "deploy_top_edge_right",
    "deploy_left_edge_top",
    "deploy_left_edge_bottom",
    "deploy_right_edge_top",
    "deploy_right_edge_bottom",
    "deploy_bottom_edge_left",
    "deploy_bottom_edge_right",
)


FALLBACK_ANCHORS: dict[str, tuple[str, ...]] = {
    "deploy_top_left": ("deploy_top_edge_left", "deploy_left_edge_top", "deploy_top_edge_right"),
    "deploy_top_mid": ("deploy_top_edge_left", "deploy_top_edge_right", "deploy_left_edge_top", "deploy_right_edge_top"),
    "deploy_top_right": ("deploy_top_edge_right", "deploy_right_edge_top", "deploy_top_edge_left"),
    "deploy_left_mid": ("deploy_left_edge_top", "deploy_left_edge_bottom", "deploy_top_edge_left"),
    "deploy_right_mid": ("deploy_right_edge_top", "deploy_right_edge_bottom", "deploy_top_edge_right"),
    "deploy_bottom_left": ("deploy_left_edge_bottom", "deploy_bottom_edge_left", "deploy_left_edge_top"),
    "deploy_bottom_mid": ("deploy_left_edge_bottom", "deploy_right_edge_bottom", "deploy_top_edge_left", "deploy_top_edge_right"),
    "deploy_bottom_right": ("deploy_right_edge_bottom", "deploy_bottom_edge_right", "deploy_right_edge_top"),
    "deploy_bottom_edge_left": ("deploy_left_edge_bottom", "deploy_top_edge_left", "deploy_right_edge_bottom"),
    "deploy_bottom_edge_right": ("deploy_right_edge_bottom", "deploy_top_edge_right", "deploy_left_edge_bottom"),
}


@dataclass(frozen=True)
class SafeBounds:
    left: int
    top: int
    right: int
    bottom: int

    @classmethod
    def from_screen(cls, width: int, height: int, config: dict[str, Any]) -> SafeBounds:
        raw = config.get("safe_bounds", {})
        if not isinstance(raw, dict):
            raw = {}
        return cls(
            left=int(raw.get("left", round(width * 0.056))),
            top=int(raw.get("top", round(height * 0.047))),
            right=int(raw.get("right", round(width * 0.944))),
            bottom=int(raw.get("bottom", round(height * 0.824))),
        )

    def contains(self, point: Point) -> bool:
        x, y = point
        return self.left <= x <= self.right and self.top <= y <= self.bottom

    def clamp_x(self, point: Point) -> Point:
        x, y = point
        return min(max(x, self.left), self.right), y


class DeploymentPerimeter:
    def __init__(
        self,
        coords: np.ndarray,
        profile: dict[str, Any],
        screen: tuple[int, int],
        *,
        tap_offset_px: int = 42,
        safe_bounds: SafeBounds | None = None,
    ) -> None:
        if len(coords) < 100:
            raise PerimeterDetectionError("not enough red boundary pixels found")

        self.coords = coords.astype(float)
        self.profile = profile
        self.screen = screen
        self.width, self.height = screen
        self.center = np.array([self.width / 2, self.height / 2], dtype=float)
        self.tap_offset_px = tap_offset_px
        self.safe_bounds = safe_bounds or SafeBounds.from_screen(self.width, self.height, {})
        self._edge_points = self._build_edge_points()
        self._fallback_counts: dict[str, int] = {}

    @classmethod
    def from_image(
        cls,
        image_path: str | Path,
        profile: dict[str, Any],
        screen: tuple[int, int],
    ) -> DeploymentPerimeter:
        config = _deployment_config(profile)
        image = Image.open(image_path).convert("RGB")
        if image.size != screen:
            image = image.resize(screen)

        mask = _red_boundary_mask(np.asarray(image), config)
        y_values, x_values = np.where(mask)
        coords = np.stack([x_values, y_values], axis=1)
        offset = int(config.get("tap_offset_px", 42))
        bounds = SafeBounds.from_screen(screen[0], screen[1], config)
        return cls(coords, profile, screen, tap_offset_px=offset, safe_bounds=bounds)

    def resolve(self, anchor: str, static_point: Point) -> Point:
        point = self._point_for(static_point)
        if point and self.safe_bounds.contains(point):
            return point

        point = self._edge_points.get(anchor)
        if point and self.safe_bounds.contains(point):
            return point

        for fallback in self._fallback_order(anchor):
            point = self._edge_points.get(fallback)
            if point and self.safe_bounds.contains(point):
                return point

        if self._edge_points:
            ordered = sorted(
                self._edge_points.values(),
                key=lambda candidate: _distance_squared(candidate, static_point),
            )
            return ordered[0]

        raise PerimeterDetectionError(f"could not find a safe deployment point for {anchor!r}")

    def _build_edge_points(self) -> dict[str, Point]:
        points: dict[str, Point] = {}
        for anchor in EDGE_ANCHORS:
            try:
                static = resolve_point(anchor, self.profile, self.screen)
            except (KeyError, ValueError):
                continue
            point = self._point_for(static)
            if not point:
                continue

            # X can safely be clipped back onto the mirror; Y outside the playfield
            # usually means the tap is on top text or the troop bar, so reject it.
            clipped = self.safe_bounds.clamp_x(point)
            if self.safe_bounds.contains(clipped):
                points[anchor] = clipped
        return points

    def _point_for(self, static_point: Point) -> Point | None:
        direction = np.array(static_point, dtype=float) - self.center
        norm = float(np.linalg.norm(direction))
        if norm < 1:
            return None
        unit = direction / norm

        relative = self.coords - self.center
        projection = relative @ unit
        perpendicular = np.abs(relative[:, 0] * unit[1] - relative[:, 1] * unit[0])
        keep = (projection > 40) & (perpendicular < np.maximum(65, projection * 0.20))
        if not np.any(keep):
            return None

        candidates = self.coords[keep]
        score = projection[keep] - 1.2 * perpendicular[keep]
        boundary = candidates[int(np.argmax(score))]
        tap = boundary + unit * self.tap_offset_px
        return round(float(tap[0])), round(float(tap[1]))

    def _fallback_order(self, anchor: str) -> tuple[str, ...]:
        configured = FALLBACK_ANCHORS.get(anchor, ())
        available = tuple(name for name in configured if name in self._edge_points)
        if len(available) <= 1:
            return available

        count = self._fallback_counts.get(anchor, 0)
        self._fallback_counts[anchor] = count + 1
        start = count % len(available)
        return available[start:] + available[:start]


def auto_adjust_anchor(target: Any, profile: dict[str, Any]) -> str | None:
    anchor: str | None = None
    if isinstance(target, str):
        anchor = target
    elif isinstance(target, dict) and isinstance(target.get("anchor"), str):
        if target.get("auto_perimeter") is False:
            return None
        anchor = target["anchor"]

    if not anchor or not anchor.startswith("deploy_"):
        return None
    if not _deployment_config(profile).get("auto_perimeter", False):
        return None
    return anchor


def _deployment_config(profile: dict[str, Any]) -> dict[str, Any]:
    config = profile.get("deployment", {})
    return config if isinstance(config, dict) else {}


def _red_boundary_mask(pixels: np.ndarray, config: dict[str, Any]) -> np.ndarray:
    red = pixels[:, :, 0].astype(np.int16)
    green = pixels[:, :, 1].astype(np.int16)
    blue = pixels[:, :, 2].astype(np.int16)

    mask = (
        (red > int(config.get("red_min", 130)))
        & (green > int(config.get("green_min", 35)))
        & (green < int(config.get("green_max", 150)))
        & (blue < int(config.get("blue_max", 115)))
        & ((red - blue) > int(config.get("red_blue_delta_min", 45)))
        & ((red - green) > int(config.get("red_green_delta_min", 18)))
    )

    height, width = mask.shape
    mask[: round(height * 0.042), :] = False
    mask[round(height * 0.844) :, :] = False
    mask[:, : round(width * 0.056)] = False
    mask[:, round(width * 0.944) :] = False

    _clear(mask, 0, 0, round(width * 0.138), round(height * 0.289))
    _clear(mask, round(width * 0.819), 0, width, round(height * 0.211))
    _clear(mask, 0, round(height * 0.678), round(width * 0.144), round(height * 0.844))
    _clear(mask, round(width * 0.825), round(height * 0.667), width, round(height * 0.844))

    for region in config.get("exclude_regions", []):
        if not isinstance(region, dict):
            continue
        _clear(
            mask,
            _scale(region.get("x1", 0), width),
            _scale(region.get("y1", 0), height),
            _scale(region.get("x2", 0), width),
            _scale(region.get("y2", 0), height),
        )

    return _neighbor_filter(mask)


def _neighbor_filter(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    neighbor_count = np.zeros_like(mask, dtype=np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            shifted = np.zeros_like(mask)
            target_y = slice(max(0, dy), height + min(0, dy))
            target_x = slice(max(0, dx), width + min(0, dx))
            source_y = slice(target_y.start - dy, target_y.stop - dy)
            source_x = slice(target_x.start - dx, target_x.stop - dx)
            shifted[target_y, target_x] = mask[source_y, source_x]
            neighbor_count += shifted
    return mask & (neighbor_count >= 2)


def _clear(mask: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> None:
    height, width = mask.shape
    left = min(max(x1, 0), width)
    right = min(max(x2, 0), width)
    top = min(max(y1, 0), height)
    bottom = min(max(y2, 0), height)
    if right > left and bottom > top:
        mask[top:bottom, left:right] = False


def _scale(value: object, max_value: int) -> int:
    if isinstance(value, float) and 0 <= value <= 1:
        return round(value * max_value)
    return round(float(value))


def _distance_squared(a: Point, b: Point) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
