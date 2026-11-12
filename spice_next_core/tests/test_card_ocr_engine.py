"""Tests for the Card OCR engine (vision, two-line split, grammar). No Frappe, no database: they draw a card, photograph it at an angle, and run the path."""

import unittest

import cv2
import numpy as np

from spice_next_core.card_ocr.engine import grammar, twoline, vision

W, H = 2000, 1400
ROWS = ["weight_kg", "pulse", "bp", "date"]
COL_X = [200, 700, 1200, 1700]          # 3 visit columns
ROW_Y = [300, 500, 700, 900, 1100]      # 4 rows


def blank_card():
	img = np.full((H, W), 255, np.uint8)
	rng = np.random.RandomState(7)
	placed = 0
	while placed < 160:                 # printed text gives SIFT something to match; kept outside the table so no cell has print in it
		x, y = int(rng.randint(20, W - 160)), int(rng.randint(40, H - 20))
		if COL_X[0] - 30 <= x <= COL_X[-1] + 30 and ROW_Y[0] - 60 <= y <= ROW_Y[-1] + 30:
			continue
		cv2.putText(img, "".join(rng.choice(list("ABCDEFGHKMNPRSTUWXYZ0123456789"), 6)), (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, int(rng.randint(0, 110)), 2)
		placed += 1
	for x in COL_X:
		cv2.line(img, (x, ROW_Y[0]), (x, ROW_Y[-1]), 0, 3)
	for y in ROW_Y:
		cv2.line(img, (COL_X[0], y), (COL_X[-1], y), 0, 3)
	return img


def grid():
	return {"image_size": [W, H], "rows": ROWS, "y_ref_top": float(ROW_Y[0]), "y_ref_bot": float(ROW_Y[-1]),
		"col_lines_top": [float(x) for x in COL_X], "col_lines_bot": [float(x) for x in COL_X],
		"row_lines_by_col": [[float(y) for y in ROW_Y] for _ in range(3)]}


def write(img, row, col, strokes=6):
	"""Draw handwriting-like strokes inside one cell."""
	x0, x1, y0, y1 = COL_X[col] + 40, COL_X[col + 1] - 40, ROW_Y[row] + 40, ROW_Y[row + 1] - 40
	rng = np.random.RandomState(row * 10 + col)
	for _ in range(strokes):
		pts = np.int32([[rng.randint(x0, x1), rng.randint(y0, y1)] for _ in range(4)])
		cv2.polylines(img, [pts.reshape(-1, 1, 2)], False, 0, 6)


def photograph(img):
	"""A skewed, slightly shrunk photo of the card with a different background."""
	src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
	dst = np.float32([[90, 60], [1750, 120], [1700, 1230], [140, 1180]])
	M = cv2.getPerspectiveTransform(src, dst)
	out = cv2.warpPerspective(img, M, (1850, 1300), borderValue=180)
	return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)


class VisionPath(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.template = blank_card()
		cls.target = vision.Target("synth", cls.template, grid())
		filled = cls.template.copy()
		cls.written = {(0, 0), (1, 2), (3, 1)}
		for r, c in cls.written:
			write(filled, r, c)
		cls.result = vision.process(photograph(filled), [cls.target])

	def test_card_is_identified(self):
		self.assertEqual(self.result["card"], "synth")
		self.assertGreaterEqual(self.result["inliers"], vision.MIN_INLIERS)

	def test_every_grid_cell_is_cut(self):
		self.assertEqual(len(self.result["cells"]), len(ROWS) * 3)

	def test_ink_is_found_in_exactly_the_written_cells(self):
		got = {(c["row"], c["col"]) for c in self.result["cells"] if c["ink"]}
		self.assertEqual(got, self.written)

	def test_visit_and_field_names(self):
		names = {(c["field"], c["visit"]) for c in self.result["cells"]}
		self.assertIn(("weight_kg", "c1"), names)
		self.assertIn(("date", "c3"), names)

	def test_a_photo_of_another_card_is_rejected(self):
		other = np.full((1000, 1400, 3), 255, np.uint8)
		rng = np.random.RandomState(99)
		for _ in range(120):
			cv2.putText(other, "Q%dZ" % rng.randint(1000), (int(rng.randint(10, 1200)), int(rng.randint(30, 980))), cv2.FONT_HERSHEY_PLAIN, 2, (0, 0, 0), 2)
		res = vision.process(other, [self.target])
		self.assertEqual(res["status"], "rejected")
		self.assertEqual(res["cells"], [])

	def test_unreadable_bytes_give_none(self):
		self.assertIsNone(vision.decode_image(b"not an image"))


class Prepare(unittest.TestCase):
	def test_blank_cell_never_reaches_a_reader(self):
		self.assertIsNone(vision.prepare(np.full((120, 400), 255, np.uint8)))

	def test_written_cell_fits_48_by_192(self):
		c = np.full((120, 400), 255, np.uint8)
		cv2.polylines(c, [np.int32([[60, 30], [200, 90], [300, 40]]).reshape(-1, 1, 2)], False, 0, 8)
		out = vision.prepare(c)
		self.assertEqual(out.shape, (48, 192))

	def test_ruled_lines_alone_are_not_ink(self):
		c = np.full((120, 400), 255, np.uint8)
		cv2.line(c, (0, 60), (399, 60), 0, 3)
		self.assertFalse(vision.has_ink(vision.Target("t", blank_card(), grid()), c))


class TwoLine(unittest.TestCase):
	def test_stacked_pieces_separate_top_and_bottom(self):
		g = np.full((100, 300), 255, np.uint8)
		cv2.line(g, (10, 50), (290, 50), 0, 3)                      # the fraction bar
		cv2.polylines(g, [np.int32([[40, 10], [120, 35]]).reshape(-1, 1, 2)], False, 0, 5)        # top
		cv2.polylines(g, [np.int32([[40, 70], [120, 92]]).reshape(-1, 1, 2)], False, 0, 5)        # bottom
		top, bottom = twoline.parts(g, "stacked")
		self.assertGreater((top[:48] < 128).sum(), 0)
		self.assertEqual((top[55:] < 128).sum(), 0)
		self.assertGreater((bottom[55:] < 128).sum(), 0)
		self.assertEqual((bottom[:45] < 128).sum(), 0)

	def test_diagonal_pieces_split_corner_to_corner(self):
		g = np.full((100, 300), 255, np.uint8)
		cv2.polylines(g, [np.int32([[20, 30], [90, 20]]).reshape(-1, 1, 2)], False, 0, 5)        # above the diagonal
		cv2.polylines(g, [np.int32([[210, 80], [280, 90]]).reshape(-1, 1, 2)], False, 0, 5)      # below it
		a, b = twoline.parts(g, "diagonal")
		self.assertGreater((a[:, :150] < 128).sum(), 0)
		self.assertEqual((a[:, 220:] < 128).sum(), 0)
		self.assertGreater((b[:, 200:] < 128).sum(), 0)

	def test_labels_split_and_join(self):
		self.assertEqual(twoline.split_label("stacked", "22.2/26"), ("22.2", "26"))
		self.assertEqual(twoline.split_label("diagonal", "120/80"), ("120", "80"))
		self.assertIsNone(twoline.split_label("diagonal", "120"))
		self.assertEqual(twoline.join("stacked", "22.2", "26"), "22/2/26")
		self.assertEqual(twoline.join("diagonal", "", "80"), "")


class Grammar(unittest.TestCase):
	def test_number_grammar_candidates_cover_ints_and_decimals(self):
		c = grammar.candidates("number", (30, 150))
		self.assertIn("57", c)
		self.assertIn("57.4", c)
		self.assertNotIn("7", c)

	def test_decode_picks_the_legal_value(self):
		chars = ["0", "1", "2", "5", "7", "<blank>"]
		# steps spelling "5", "7" with high scores
		lg = np.full((4, 6), -6.0)
		lg[0, 3] = 6.0
		lg[1, 5] = 6.0
		lg[2, 4] = 6.0
		lg[3, 5] = 6.0
		text, margin = grammar.decode(lg, chars, 5, "number", (30, 150))
		self.assertEqual(text, "57")


if __name__ == "__main__":
	unittest.main()


class GridFinder(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		from spice_next_core.card_ocr.engine import gridfinder
		cls.gf = gridfinder
		cls.tpl = blank_card()

	def test_finds_the_printed_rules(self):
		ln = self.gf.find_lines(self.tpl)
		self.assertEqual(len(ln["h"]), len(ROW_Y))
		self.assertEqual(len(ln["v"]), len(COL_X))
		for got, want in zip(ln["h"], ROW_Y):
			self.assertAlmostEqual(got, want, delta=3)
		for got, want in zip(ln["v"], COL_X):
			self.assertAlmostEqual(got, want, delta=3)

	def test_proposed_grid_is_valid_and_has_the_right_shape(self):
		g = self.gf.propose_grid(self.tpl)
		self.assertEqual(vision.check_grid(g), [])
		self.assertEqual((len(g["rows"]), len(g["col_lines_top"]) - 1), (4, 3))

	def test_columns_axis_names_fields_by_column(self):
		g = self.gf.propose_grid(self.tpl, axis="columns")
		self.assertEqual(vision.check_grid(g), [])
		self.assertEqual(g["cols"], ["f1", "f2", "f3"])

	def test_studios_layout_detection_gives_the_right_grid_on_a_thick_ruled_card(self):
		r = self.gf.propose(self.tpl)
		g = r["grid"]
		self.assertEqual(r["method"], "layout")
		self.assertEqual((len(g["rows"]), len(g["col_lines_top"]) - 1), (4, 3))
		self.assertEqual(vision.check_grid(g), [])
		for got, want in zip(g["row_lines_by_col"][0], ROW_Y):
			self.assertAlmostEqual(got, want, delta=6)

	def test_merge_thin_rows_only_touches_hairline_bands(self):
		g = {"image_size": [1000, 1000], "rows": ["a", "b", "c"], "y_ref_top": 100.0, "y_ref_bot": 400.0, "col_lines_top": [0, 500, 1000], "col_lines_bot": [0, 500, 1000],
			"row_lines_by_col": [[100.0, 200.0, 204.0, 400.0]] * 2}
		out, n = self.gf.merge_thin_rows(g)
		self.assertEqual((n, out["rows"]), (1, ["a", "c"]))
		self.assertEqual(out["row_lines_by_col"][0], [100.0, 200.0, 400.0])
		clean = {**g, "rows": ["a", "b"], "row_lines_by_col": [[100.0, 200.0, 400.0]] * 2}
		self.assertEqual(self.gf.merge_thin_rows(clean)[1], 0)

	def test_a_blank_image_proposes_nothing(self):
		self.assertIsNone(self.gf.propose_grid(np.full((600, 800), 255, np.uint8)))

	def test_grid_check_rejects_bad_geometry(self):
		g = self.gf.propose_grid(self.tpl)
		g["col_lines_top"] = list(reversed(g["col_lines_top"]))
		self.assertTrue(vision.check_grid(g))


class Formats(unittest.TestCase):
	def test_heic_with_a_png_name_is_read_when_pillow_heif_is_installed(self):
		import io

		from PIL import Image
		try:
			import pillow_heif
		except ImportError:
			self.skipTest("pillow-heif is not installed")
		pillow_heif.register_heif_opener()
		buf = io.BytesIO()
		Image.fromarray(np.full((120, 200, 3), 200, np.uint8)).save(buf, format="HEIF")
		im = vision.decode_image(buf.getvalue())
		self.assertEqual(im.shape[:2], (120, 200))

	def test_png_and_jpeg_still_read_through_opencv(self):
		img = np.full((50, 80, 3), 120, np.uint8)
		for ext in (".png", ".jpg"):
			self.assertEqual(vision.decode_image(cv2.imencode(ext, img)[1].tobytes()).shape[:2], (50, 80))

	def test_a_pdf_or_junk_is_none(self):
		self.assertIsNone(vision.decode_image(b"%PDF-1.4 not an image"))
		self.assertIsNone(vision.decode_image(b"\x00\x00\x00\x20ftypheic" + b"\x00" * 40))


class Normalize(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		from spice_next_core.card_ocr.engine import normalize
		cls.N = normalize

	def test_methods_and_labels_agree(self):
		self.assertEqual(set(self.N.METHODS), set(self.N.LABELS))
		self.assertIn("flatten", self.N.METHODS)

	def test_histogram_stats(self):
		g = np.concatenate([np.full(50, 100, np.uint8), np.full(50, 200, np.uint8)])
		mean, std = self.N.hist_stats(self.N.hist256(g))
		self.assertAlmostEqual(mean, 150.0)
		self.assertAlmostEqual(std, 50.0)

	def test_contrast_match_moves_the_page_to_the_reference(self):
		page = np.where(np.arange(10000).reshape(100, 100) % 2 == 0, 60, 120).astype(np.uint8)
		covered = np.ones_like(page)
		out, used = self.N.normalize_page("contrast_match", page, covered, 61, (200.0, 40.0))
		self.assertEqual(used, "contrast_match")
		self.assertAlmostEqual(float(out.mean()), 200.0, delta=2)
		self.assertAlmostEqual(float(out.std()), 40.0, delta=2)

	def test_contrast_match_without_a_reference_falls_back_to_flatten(self):
		page = np.full((80, 80), 150, np.uint8)
		_out, used = self.N.normalize_page("contrast_match", page, np.ones_like(page), 21, None)
		self.assertEqual(used, "flatten")

	def test_flatten_evens_out_a_shadow(self):
		page = np.full((120, 200), 230, np.uint8)
		page[:, 100:] = 140                                             # half the page is in shadow
		out, _ = self.N.normalize_page("flatten", page, np.ones_like(page), 41, None)
		self.assertLess(abs(float(out[:, :90].mean()) - float(out[:, 110:].mean())), 12)

	def test_stretch_leaves_a_flat_cell_alone(self):
		flat = np.full((40, 80), 200, np.uint8)
		self.assertTrue((self.N.stretch_cell(flat) == flat).all())

	def test_none_returns_the_page_unchanged(self):
		page = np.random.RandomState(1).randint(0, 255, (50, 50)).astype(np.uint8)
		out, used = self.N.normalize_page("none", page, np.ones_like(page), 21, None)
		self.assertTrue((out == page).all())
		self.assertEqual(used, "none")

	def test_unknown_method_is_refused(self):
		with self.assertRaises(ValueError):
			self.N.normalize_page("sharpen", np.zeros((5, 5), np.uint8), np.ones((5, 5), np.uint8), 5, None)


class Pdf(unittest.TestCase):
	def test_every_page_of_a_pdf_is_an_image(self):
		import io

		from PIL import Image
		a, b = Image.new("RGB", (300, 400), "white"), Image.new("RGB", (300, 400), "gray")
		buf = io.BytesIO()
		a.save(buf, format="PDF", save_all=True, append_images=[b])
		pages = list(vision.pages_from(buf.getvalue()))
		self.assertEqual(len(pages), 2)
		self.assertEqual(pages[0].ndim, 3)

	def test_an_image_is_one_page_and_junk_raises(self):
		img = np.full((40, 60, 3), 90, np.uint8)
		self.assertEqual(len(list(vision.pages_from(cv2.imencode(".png", img)[1].tobytes()))), 1)
		with self.assertRaises(ValueError):
			list(vision.pages_from(b"not an image at all"))


class GridFromARealCard(unittest.TestCase):
	"""Card Studio's layout detection on the real ANC template, scored against the pack's own (hand-checked) grid."""

	PACK = __import__("os").environ.get("CARD_OCR_TEST_PACK", "")      # path of a real ANC .cardpack; the test is skipped without it

	def setUp(self):
		import os
		if not self.PACK or not os.path.exists(self.PACK):
			self.skipTest("set CARD_OCR_TEST_PACK to a real ANC .cardpack to run this")

	def test_data_cols_hint_recovers_the_anc_grid(self):
		import json
		import zipfile

		from spice_next_core.card_ocr.engine import gridfinder
		z = zipfile.ZipFile(self.PACK)
		truth = json.loads(z.read("grid.json"))
		tpl = cv2.imdecode(np.frombuffer(z.read("template.png"), np.uint8), 0)
		r = gridfinder.propose(tpl, data_cols=6)
		g = r["grid"]
		self.assertEqual(r["method"], "layout")
		self.assertEqual(vision.check_grid(g), [])
		self.assertEqual(len(g["col_lines_top"]) - 1, 6)
		k = tpl.shape[1] / truth["image_size"][0]
		ty = [y * k for y in truth["row_lines_by_col"][0]]
		gy = [y * tpl.shape[0] / g["image_size"][1] for y in g["row_lines_by_col"][0]]
		found = sum(any(abs(a - b) <= 6 for b in gy) for a in ty)
		spurious = sum(not any(abs(a - b) <= 6 for b in ty) for a in gy)
		self.assertLessEqual(abs(len(g["rows"]) - len(truth["rows"])), 1)          # one true line may be missed; none may be invented in bulk
		self.assertLessEqual(spurious, 1)
		self.assertGreaterEqual(found, 20)         # at least 20 of the 23 true row lines


class Deskew(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		from spice_next_core.card_ocr.engine import deskew, layout
		cls.deskew, cls.layout = deskew, layout
		cls.card = cv2.cvtColor(blank_card(), cv2.COLOR_GRAY2BGR)

	def tilted(self, deg):
		return self.deskew.rotate_by(self.card, deg)

	def test_quarter_turns_swap_the_size(self):
		h, w = self.card.shape[:2]
		self.assertEqual(self.deskew.rotate_quarter(self.card, 90).shape[:2], (w, h))
		self.assertEqual(self.deskew.rotate_quarter(self.card, 180).shape[:2], (h, w))
		with self.assertRaises(ValueError):
			self.deskew.rotate_quarter(self.card, 45)

	def test_a_tilted_card_is_levelled(self):
		im, info = self.deskew.straighten(self.tilted(3.0))
		self.assertTrue(info["straightened"], info)
		self.assertAlmostEqual(abs(info["tilt_deg"]), 3.0, delta=0.6)
		self.assertGreater(self.deskew.line_strength(im), self.deskew.line_strength(self.tilted(3.0)))

	def test_a_level_card_is_left_alone(self):
		_im, info = self.deskew.straighten(self.card)
		self.assertFalse(info["straightened"])

	def test_levelling_can_be_switched_off(self):
		_im, info = self.deskew.straighten(self.tilted(3.0), enabled=False)
		self.assertFalse(info["straightened"])

	def test_the_cells_are_found_after_levelling_a_tilted_card(self):
		im, _ = self.deskew.straighten(self.tilted(2.5))
		det = self.layout.detect_layout(im)
		self.assertGreaterEqual(det["stats"]["cells"], 10)

	def test_a_blank_image_is_not_rotated_by_noise(self):
		_im, info = self.deskew.straighten(np.full((400, 600, 3), 255, np.uint8))
		self.assertFalse(info["straightened"])
