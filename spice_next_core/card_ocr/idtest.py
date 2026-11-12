"""Template ID test: does the system tell its own cards apart? Each card type's template is shown to the matcher among all card types; the right card
must win, and no other card may accept it. With one card type the test is trivial and says so."""
import cv2
import frappe

from spice_next_core.card_ocr import service
from spice_next_core.card_ocr.engine import vision


def run():
	"""-> {cards, self_ok, wrongly_accepted, rows: [{probe, winner, inliers, runner_up}], note}."""
	names = service.ready_cards()
	if not names:
		return {"cards": 0, "self_ok": 0, "wrongly_accepted": 0, "rows": [], "note": "No card has a template and a grid yet."}
	targets = [service.card_target(n) for n in names]
	rows, ok, wrong = [], 0, 0
	for t in targets:
		probe = cv2.cvtColor(t.tpl, cv2.COLOR_GRAY2BGR)
		winner, _H, tried = vision.identify(probe, targets)
		picked = winner.card if winner else None
		ok += 1 if picked == t.card else 0
		wrong += 1 if picked not in (None, t.card) else 0
		rows.append({"probe": t.card, "winner": picked, "inliers": tried[0]["inliers"] if tried else 0, "runner_up": tried[1]["inliers"] if len(tried) > 1 else 0})
	note = "Only one card type: this only shows that a card matches itself." if len(names) == 1 else ""
	return {"cards": len(names), "self_ok": ok, "wrongly_accepted": wrong, "rows": rows, "note": note}
