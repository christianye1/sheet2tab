"""Detects guitar TAB staffs (6 lines) in a photo, so we can refuse sheets that already have tab.

oemer only knows 5-line staffs; TAB staffs confuse its geometry code and it crashes after
minutes of work. Counting evenly spaced horizontal lines takes well under a second.
"""
from __future__ import annotations

import cv2
import numpy as np

# Several 6-line groups are needed, so one misread staff (e.g. a ledger line merging
# into a 5-line staff) doesn't trigger it.
MIN_TAB_STAFFS = 2


def staff_line_groups(img: np.ndarray, bands: int = 4) -> list[int]:
    """Sizes of groups of evenly spaced horizontal lines (5 = staff, 6 = TAB staff).

    The page is split into vertical bands that are measured separately, which tolerates
    a slight tilt; each staff is therefore counted about once per band.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape
    scale = 2000 / max(h, w)
    gray = cv2.resize(gray, (int(w * scale), int(h * scale)))
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15)

    sizes = []
    band_w = gray.shape[1] // bands
    for b in range(bands):
        band = binary[:, b * band_w:(b + 1) * band_w]
        # Keep only long horizontal runs: staff lines, not note stems or text.
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (band_w // 2, 1))
        lines = cv2.morphologyEx(band, cv2.MORPH_OPEN, kernel)
        rows = np.where(lines.sum(axis=1) / 255 > band_w * 0.6)[0]

        # A line is a few pixels thick: merge adjacent rows into one centre.
        runs: list[list[int]] = []
        for r in rows:
            if runs and r - runs[-1][-1] <= 2:
                runs[-1].append(r)
            else:
                runs.append([r])
        ys = [float(np.mean(run)) for run in runs]

        # Consecutive lines with (nearly) the same spacing belong to one staff.
        group = ys[:1]
        for y in ys[1:]:
            gap = y - group[-1]
            if len(group) >= 2:
                prev = group[-1] - group[-2]
                same_staff = abs(gap - prev) <= max(2, 0.25 * prev)
            else:
                same_staff = 5 <= gap <= 40
            if same_staff:
                group.append(y)
            else:
                sizes.append(len(group))
                group = [y]
        if group:
            sizes.append(len(group))
    return [s for s in sizes if s >= 4]


def has_tab_staffs(img: np.ndarray) -> bool:
    return staff_line_groups(img).count(6) >= MIN_TAB_STAFFS
