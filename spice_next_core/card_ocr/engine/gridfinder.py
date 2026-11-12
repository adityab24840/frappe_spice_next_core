"""Propose a grid from a card's template image by finding its long printed rules. A starting point for the grid editor, never the final word:
merged headers, double rules and faded printing need a person to adjust the lines.

Assumes a flat, straight-on template. Rows are the bands between neighbouring horizontal rules, columns the bands between vertical rules.
"""
import cv2
import numpy as np

MIN_LINE_FRACTION = 0.12     # a rule must span at least this share of the image's width (horizontal) or height (vertical)
MERGE_PX = 8                 # rules closer than this are one thick rule
PEAK = 0.35                  # a row/column of the projection counts as a rule when it reaches this share of the strongest one


def _centres(profile, merge=MERGE_PX, peak=PEAK):
	"""Positions of the rules in a 1-D projection: runs above the threshold, merged when close, as their centres."""
	if profile.max() <= 0:
		return []
	hot = np.flatnonzero(profile >= peak * profile.max())
	if hot.size == 0:
		return []
	runs, start, prev = [], hot[0], hot[0]
	for v in hot[1:]:
		if v - prev > merge:
			runs.append((start, prev))
			start = v
		prev = v
	runs.append((start, prev))
	return [float((a + b) / 2) for a, b in runs]


def find_lines(gray):
	"""-> {"h": [y of each horizontal rule], "v": [x of each vertical rule]}, each ascending, only rules inside the table."""
	H, W = gray.shape
	ink = (gray < 140).astype(np.uint8) * 255
	hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, int(W * MIN_LINE_FRACTION)), 1))
	vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, int(H * MIN_LINE_FRACTION))))
	h_img = cv2.morphologyEx(ink, cv2.MORPH_OPEN, hk)
	v_img = cv2.morphologyEx(ink, cv2.MORPH_OPEN, vk)
	ys = _centres(h_img.sum(axis=1).astype(float))
	xs = _centres(v_img.sum(axis=0).astype(float))
	return {"h": ys, "v": xs}


def propose_grid(gray, axis="rows"):
	"""-> a grid dict (as service.set_template takes) with rows named r1.. (or cols for axis columns), or None when fewer than two rules each way are found.
	Fields are the rows (axis rows) or the columns (axis columns); the other direction is the visits."""
	H, W = gray.shape
	ln = find_lines(gray)
	h, v = ln["h"], ln["v"]
	if len(h) < 2 or len(v) < 2:
		return None
	nrows, ncols = len(h) - 1, len(v) - 1
	grid = {"image_size": [W, H], "rows": [f"r{i + 1}" for i in range(nrows)], "y_ref_top": h[0], "y_ref_bot": h[-1],
		"col_lines_top": v, "col_lines_bot": list(v), "row_lines_by_col": [list(h) for _ in range(ncols)]}
	if axis == "columns":
		grid["axis"], grid["cols"] = "columns", [f"f{i + 1}" for i in range(ncols)]
	return grid


THIN_PX = 8       # a band this thin is one thick rule seen as two lines, not a row (Card Studio warns about the same)


def merge_thin_rows(grid, thin=THIN_PX):
	"""Drop row bands thinner than `thin` template pixels (a thick printed rule detected as two lines): the second line of the pair goes, the band's name
	goes with it. -> (grid, how many bands were merged). Works per column on the reference column's bands."""
	rl0 = grid["row_lines_by_col"][0]
	scale = grid["image_size"][1]
	gone = [i for i in range(len(rl0) - 1) if rl0[i + 1] - rl0[i] < thin * max(1.0, scale / 1000)]
	if not gone or len(rl0) - 1 - len(gone) < 1:
		return grid, 0
	drop_lines = {i + 1 if i + 1 < len(rl0) - 1 else i for i in gone}           # the last band: keep the line above it
	keep = [j for j in range(len(rl0)) if j not in drop_lines]
	names_keep = [i for i in range(len(rl0) - 1) if i not in gone]
	out = dict(grid)
	out["row_lines_by_col"] = [[col[j] for j in keep] for col in grid["row_lines_by_col"]]
	out["rows"] = [grid["rows"][i] for i in names_keep]
	if len(out["rows"]) != len(keep) - 1:             # names and lines disagree: leave the grid as it was rather than guess
		return grid, 0
	out["y_ref_top"], out["y_ref_bot"] = out["row_lines_by_col"][0][0], out["row_lines_by_col"][0][-1]
	return out, len(gone)


def propose(gray, axis="rows", label_cols=0, data_cols=None, label_rows=0, data_rows=None):
	"""-> {"grid", "method", "warnings"}. First Card Studio's own layout detection (engine/layout.py: cells found with OpenCV, then voted into column and
	row lines, which copes with merged cells and a slightly skewed card); when it finds no table, the simpler rule finder above. grid is None when neither does.
	label_cols / data_cols / label_rows / data_rows are Studio's hints: skip that many leading printed columns or heading rows, keep only that many data columns
	or rows. On the ANC template, data_cols=6 turns a 31-row layout into the card's real 22-row, 6-visit grid."""
	from spice_next_core.card_ocr.engine import layout

	try:
		bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR) if gray.ndim == 2 else gray
		det = layout.detect_layout(bgr)
		grid, warnings = layout.layout_to_grid({"image": det["stats"]["image"], "fields": det["fields"]}, axis=axis, label_cols=label_cols, data_cols=data_cols or None, label_rows=label_rows, data_rows=data_rows or None)
		grid, merged = merge_thin_rows(grid)
		if merged:
			warnings = [w for w in warnings if "under 8 px" not in w] + [f"{merged} hair-thin row band(s) were merged: a thick printed rule had been read as two lines"]
		return {"grid": grid, "method": "layout", "warnings": warnings}
	except (ValueError, KeyError, IndexError):
		return {"grid": propose_grid(gray, axis), "method": "lines", "warnings": []}
