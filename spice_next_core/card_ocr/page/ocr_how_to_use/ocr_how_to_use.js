// How to use: the whole workflow, in order, and the rules that keep the numbers honest.
frappe.pages["ocr-how-to-use"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("How to use"), single_column: true });
	const step = (n, t, body, route) => `<div class="cs-step"><div class="cs-dot done" style="display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px">${n}</div>
		<div><div class="t" style="text-decoration:none;color:inherit;font-weight:600">${route ? `<a href="/app/${route}">${t}</a>` : t}</div><div class="d">${body}</div></div></div>`;
	$(`<div class="cs"><style>
.cs { width: 100%; max-width: 1280px; }
.cs-eyebrow { text-transform: uppercase; letter-spacing: .08em; font-size: 11px; color: var(--text-muted); }
.cs-title { font-size: 24px; font-weight: 600; margin: 2px 0 6px; }
.cs-lead { color: var(--text-muted); max-width: 720px; margin-bottom: 10px; }
.cs-pills { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 18px; }
.cs-pill { display: inline-block; padding: 2px 10px; border-radius: 6px; font-size: 12px; background: var(--control-bg); color: var(--text-color); }
.cs-pill.ok { background: var(--bg-green); color: var(--green-700, #15803d); }
.cs-pill.warn { background: var(--bg-orange); color: var(--orange-700, #c2410c); }
.cs-pill.bad { background: var(--bg-red); color: var(--red-700, #b91c1c); }
.cs-pill.info { background: var(--bg-blue); color: var(--blue-700, #1d4ed8); }
.cs-panel { border: 1px solid var(--border-color); border-radius: 10px; padding: 16px 18px; margin-bottom: 16px; background: var(--card-bg); }
.cs-h { font-size: 15px; font-weight: 600; margin-bottom: 10px; }
.cs-h small { font-weight: 400; color: var(--text-muted); margin-left: 6px; }
.cs-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 18px; }
.cs-tile { border: 1px solid var(--border-color); border-radius: 10px; padding: 14px 16px; background: var(--card-bg); }
.cs-tile .k { text-transform: uppercase; letter-spacing: .06em; font-size: 11px; color: var(--text-muted); }
.cs-tile .v { font-size: 30px; font-weight: 600; margin: 4px 0 2px; }
.cs-tile .v .of { font-size: 14px; font-weight: 400; color: var(--text-muted); }
.cs-tile .v.good { color: var(--green-600, #16a34a); }
.cs-tile .s { font-size: 12px; color: var(--text-muted); }
.cs-grid2 { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 16px; }
@media (max-width: 1000px) { .cs-grid2 { grid-template-columns: 1fr; } }
.cs-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cs-table th { text-transform: uppercase; letter-spacing: .05em; font-size: 11px; font-weight: 500; color: var(--text-muted); text-align: left; padding: 6px 10px; }
.cs-table td { padding: 9px 10px; border-top: 1px solid var(--border-color); vertical-align: middle; }
.cs-chip { display: inline-flex; gap: 6px; align-items: center; border: 1px solid var(--border-color); border-radius: 6px; padding: 2px 9px; font-size: 12px; margin: 0 6px 6px 0; background: var(--control-bg); }
.cs-chip.on { border-color: var(--primary); box-shadow: 0 0 0 1px var(--primary) inset; }
.cs-chip .n { color: var(--green-600, #16a34a); }
.cs-tag { display: inline-block; border-radius: 6px; padding: 1px 8px; font-size: 12px; background: var(--control-bg); margin: 0 6px 6px 0; font-family: var(--font-stack-mono, monospace); }
.cs-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.cs-bar { height: 8px; border-radius: 4px; background: var(--control-bg); overflow: hidden; margin: 6px 0 12px; }
.cs-bar > div { height: 100%; background: var(--green-500, #22c55e); }
.cs-bar.blue > div { background: var(--primary); }
.cs-range { position: relative; width: 120px; height: 8px; border-radius: 4px; background: var(--control-bg); display: inline-block; vertical-align: middle; }
.cs-range i { position: absolute; top: 0; height: 8px; border-radius: 4px; background: var(--blue-300, #93c5fd); }
.cs-range b { position: absolute; top: -2px; width: 3px; height: 12px; background: var(--primary); border-radius: 2px; }
.cs-step { display: flex; gap: 10px; padding: 9px 0; border-top: 1px solid var(--border-color); }
.cs-step:first-of-type { border-top: 0; }
.cs-dot { flex: none; width: 18px; height: 18px; border-radius: 50%; border: 2px solid var(--border-color); margin-top: 2px; }
.cs-dot.done { background: var(--green-500, #22c55e); border-color: var(--green-500, #22c55e); }
.cs-step.done .t { text-decoration: line-through; color: var(--text-muted); }
.cs-step .d { font-size: 12px; color: var(--text-muted); }
.cs-muted { color: var(--text-muted); }
.cs-status { margin: 6px 0 10px; }
.cs-status .state { font-weight: 600; color: var(--green-600, #16a34a); margin-right: 6px; }
.cs-status .state.bad { color: var(--red-600, #dc2626); } .cs-status .state.run { color: var(--orange-600, #ea580c); }
</style>
		<div class="cs-eyebrow">${__("Guide")}</div><div class="cs-title">${__("How to use Card OCR")}</div>
		<div class="cs-lead">${__("Teach the system a handwritten health card, measure how well it reads pages it has not seen, and ship a pack to the phone.")}</div>
		<div class="cs-panel"><div class="cs-h">${__("The workflow")}</div>
			${step(1, __("Make a card type"), __("Create an OCR Card Type: a short key, a title, and its fields (kind: number, date, bp, mark or text; a range for numbers; layout stacked for a date on two lines, diagonal for a blood pressure split by a printed line)."), "ocr-card-type")}
			${step(2, __("Give it a template, then a grid"), __("Template & grid, step 1: upload a photo of the blank card (turn it if it lies on its side; it levels the ruled lines), check the cells it found, drag or resize them, rename them, Save template. Step 2: say which way the card runs, skip label columns and heading rows if rows or columns are off, Preview the grid drawn over the card, Save grid."), "ocr-grid-editor")}
			${step(3, __("Add filled scans"), __("Upload straight-on photos. Each is matched to a card, straightened and cut into cells. A photo that matches no card is rejected and nothing is stored. Set writer codes for the pages."), "ocr-scans")}
			${step(4, __("Label cells"), __("Type what each cell says. A suggestion is never a label: you confirm or correct it. Blank and unreadable cells are marked, not guessed."), "ocr-labeling")}
			${step(5, __("Train and ship"), __("Training uses only what people confirmed, on the PyTorch backend. A field ships only if the low end of its 95% interval, measured on pages the model never saw, meets the target with enough cells."), "ocr-training")}
			${step(6, __("Put the pack on the phone"), __("Download the pack from the dashboard, or let the app fetch it from the pack list. The phone reads the same pack format."), "ocr-studio")}</div>
		<div class="cs-panel"><div class="cs-h">${__("Rules that keep the numbers honest")}</div>
			<div class="cs-step"><div><div class="t" style="text-decoration:none;font-weight:600">${__("Machine reads are not labels")}</div><div class="d">${__("A reader trained on a machine's guesses is scored against the same guesses, so its accuracy means little. Such labels are left out of training unless you switch it on in OCR Settings, and a pack made with them can never be marked Shipped.")}</div></div></div>
			<div class="cs-step"><div><div class="t" style="text-decoration:none;font-weight:600">${__("Writers are codes, never names")}</div><div class="d">${__("Give each page a writer code like W07. With writers known, a test never shares a writer with training, so the held-out numbers are not flattered by one person's habits.")}</div></div></div>
			<div class="cs-step"><div><div class="t" style="text-decoration:none;font-weight:600">${__("Patient data stays private")}</div><div class="d">${__("Photos and cell crops are private files. Do not copy them out of the site.")}</div></div></div>
			<div class="cs-step"><div><div class="t" style="text-decoration:none;font-weight:600">${__("Small numbers are noise")}</div><div class="d">${__("A field with 20 held-out cells has a very wide interval. The gate asks for enough cells as well as a high accuracy.")}</div></div></div></div>
		<div class="cs-panel"><div class="cs-h">${__("Other tools")}</div>
			<div class="cs-muted">${__("Clean-up lab: how each photo clean-up method changes what the reader reads. History: runs and comparisons. Model quality: the experiments. Training page: is there enough labelled data, and the starting weights.")}</div></div></div>`).appendTo(page.main);
};
