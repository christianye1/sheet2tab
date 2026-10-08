"""Runs the oemer CLI with fixes for oemer bugs. Usage: python -m app.oemer_runner <oemer args>"""
import oemer.bbox

_merge_nearby_bbox = oemer.bbox.merge_nearby_bbox


def _safe_merge_nearby_bbox(bboxes, *args, **kwargs):
    # oemer clusters the boxes, which needs at least two; with 0 or 1 there is nothing to merge.
    # Without this, a page where e.g. only one rest is found crashes with
    # "Found array with 1 sample(s) ... required by AgglomerativeClustering".
    if len(bboxes) < 2:
        return list(bboxes)
    return _merge_nearby_bbox(bboxes, *args, **kwargs)


# Must happen before oemer.ete is imported: the oemer modules copy the function with
# `from oemer.bbox import merge_nearby_bbox` at import time.
oemer.bbox.merge_nearby_bbox = _safe_merge_nearby_bbox

from oemer.ete import main  # noqa: E402

if __name__ == "__main__":
    main()
