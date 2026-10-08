from pathlib import Path

import cv2
import numpy as np

from app.tab_detect import has_tab_staffs, staff_line_groups

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def page_with_staffs(lines_per_staff: int, staffs: int = 4) -> np.ndarray:
    img = np.full((1600, 1200, 3), 255, np.uint8)
    for s in range(staffs):
        top = 150 + s * 350
        for i in range(lines_per_staff):
            y = top + i * 18
            cv2.line(img, (80, y), (1120, y), (0, 0, 0), 2)
    return img


def test_counts_five_and_six_line_staffs():
    assert set(staff_line_groups(page_with_staffs(5))) == {5}
    assert set(staff_line_groups(page_with_staffs(6))) == {6}


def test_tab_page_is_detected():
    assert has_tab_staffs(page_with_staffs(6))
    assert not has_tab_staffs(page_with_staffs(5))


def test_real_samples_have_no_tab():
    for name in ("noten_sample.png", "noten_samples_big.png"):
        assert not has_tab_staffs(cv2.imread(str(SAMPLES / name))), name
