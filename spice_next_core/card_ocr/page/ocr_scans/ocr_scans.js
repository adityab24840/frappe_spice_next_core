// OCR Scans: upload a photo of a card; the system says which card it is, straightens it and cuts it into cells ready to label.
const API = "spice_next_core.card_ocr.api.";

frappe.pages["ocr-scans"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("OCR Scans"), single_column: true });
	new OcrScans(page);
};

class OcrScans {
	constructor(page) {
		this.page = page;
		this.card_field = page.add_field({ fieldname: "card", label: __("Card"), fieldtype: "Select", default: "auto" });
		this.writer_field = page.add_field({ fieldname: "writer", label: __("Writer code (optional)"), fieldtype: "Data", description: __("W07 or a clinic id, never a name") });
		page.set_primary_action(__("Upload photo"), () => this.upload());
		this.$body = $(`<div class="ocr-scans"></div>`).appendTo(page.main);
		$(`<style>
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
</style>`).appendTo(this.$body);
		this.$list = $(`<div></div>`).appendTo(this.$body);
		this.$writers = $(`<div class="cs-panel"></div>`).appendTo(this.$body);
		this.card_field.df.change = () => this.load_writers();
		$(`<div class="cs-eyebrow">${__("Data")}</div><div class="cs-title">${__("Add scans")}</div><p class="cs-lead">${__("Take a straight-on photo of one card. The photo is matched against every card type that has a template and a grid; if it matches none, nothing is stored.")}</p>`).prependTo(this.$body);
		this.load_cards();
	}

	async load_cards() {
		const r = await frappe.call({ method: "frappe.client.get_list", args: { doctype: "OCR Card Type", fields: ["name", "title"], limit_page_length: 200 } });
		const opts = [{ value: "auto", label: __("Detect which card") }].concat((r.message || []).map((c) => ({ value: c.name, label: c.title })));
		this.card_field.df.options = opts;
		this.card_field.refresh();
		this.card_field.set_value("auto");
		this.load_writers();
	}

	async load_writers() {
		const card = this.card_field.get_value();
		const e = frappe.utils.escape_html;
		if (!card || card === "auto") {
			this.$writers.html(`<div class="cs-h">${__("Writers")} <small>${__("choose one card to see and assign its writers")}</small></div>`);
			return;
		}
		const w = (await frappe.call({ method: API + "writer_status", type: "GET", args: { card_type: card } })).message;
		this.$writers.html(`<div class="cs-h">${__("Writers")} <small>${__("who wrote each card: a code like W07 or a clinic id, never a name")}</small></div>
			<div class="cs-status">${e(w.message)}</div>
			<div class="cs-actions" style="margin:0 0 10px">
				<input class="form-control input-sm w-code" style="width:120px" placeholder="${__("Writer code")}">
				<input class="form-control input-sm w-first" style="width:110px" placeholder="${__("first page")}">
				<input class="form-control input-sm w-last" style="width:110px" placeholder="${__("last page")}">
				<button class="btn btn-primary btn-sm w-set">${__("Set writer")}</button>
				<button class="btn btn-default btn-sm w-blank">${__("Rebuild blank card and ink flags")}</button>
			</div>
			<table class="cs-table"><tr><th>${__("Page")}</th><th>${__("Writer")}</th><th>${__("Labeled cells")}</th></tr>
			${w.rows.slice(0, 60).map((r) => `<tr><td>${e(r.page)}</td><td>${r.writer ? e(r.writer) : `<span class="cs-muted">—</span>`}</td><td>${r.labeled}</td></tr>`).join("")}</table>
			${w.rows.length > 60 ? `<div class="cs-muted">${__("showing the first 60 of {0} pages", [w.rows.length])}</div>` : ""}`);
		this.$writers.find(".w-set").on("click", async () => {
			try {
				await frappe.call({ method: API + "assign_writer", type: "POST", args: { card_type: card, writer: this.$writers.find(".w-code").val().trim(), first: this.$writers.find(".w-first").val().trim(), last: this.$writers.find(".w-last").val().trim() } });
				this.load_writers();
			} catch (_) { /* the server says why */ }
		});
		this.$writers.find(".w-blank").on("click", async () => {
			const r = (await frappe.call({ method: API + "refresh_ink", type: "POST", args: { card_type: card }, freeze: true, freeze_message: __("Rebuilding...") })).message;
			frappe.show_alert({ message: r.rebuilt ? __("Blank card rebuilt from {0} scans; {1} ink flags changed.", [r.scans, r.changed]) : __("Needs at least 5 aligned scans ({0} so far).", [r.scans]), indicator: r.rebuilt ? "green" : "orange" });
		});
	}

	upload() {
		new frappe.ui.FileUploader({
			restrictions: { allowed_file_types: ["image/*", ".pdf", ".heic"] },
			make_attachments_public: false,
			on_success: (file) => this.add(file.file_url),
		});
	}

	async add(file_url) {
		const $card = $(`<div class="cs-panel"><div class="cs-h">${__("Reading the photo...")}</div></div>`).prependTo(this.$list);
		try {
			const r = await frappe.call({
				method: API + "add_scan", type: "POST", freeze: true, freeze_message: __("Matching and cutting..."),
				args: { file_url, card_type: this.card_field.get_value() || "auto", writer: this.writer_field.get_value() || "" },
			});
			const m = r.message;
			if (m.results) {
				$card.html(`<div class="cs-h">${m.pages} ${__("pages in the PDF")} <small>${m.results.filter((x) => x.scan).length} ${__("matched,")} ${m.results.filter((x) => !x.scan).length} ${__("rejected")}</small></div>`);
				m.results.forEach((x) => { const $c = $(`<div class="cs-panel"></div>`).insertAfter($card); this.show($c, x); });
			} else this.show($card, m);
		} catch (e) {
			$card.html(`<div class="cs-h"><span class="cs-pill bad">${__("failed")}</span> ${__("Could not read this photo")}</div><div class="cs-muted">${frappe.utils.escape_html((e && e.message) || "")}</div>`);
		}
	}

	show($card, r) {
		const e = frappe.utils.escape_html;
		const tried = (r.tried || []).map((t) => `${e(t.card)}: ${t.inliers} ${__("matching features")}${t.why ? " (" + e(t.why) + ")" : ""}`).join("<br>");
		if (!r.scan) {
			$card.html(`<div class="cs-h"><span class="cs-pill bad">${__("unknown card")}</span> ${__("No card type matches this photo")}</div>
				<div class="cs-muted">${__("Nothing was stored.")}<br>${tried}</div>`);
			return;
		}
		$card.html(`
			<div class="cs-h"><span class="cs-pill ${r.status === "ok" ? "ok" : "warn"}">${r.status === "ok" ? __("matched") : __("weak match")}</span> ${e(r.card)}
				<small>${r.cells} ${__("cells")}, ${r.with_ink} ${__("with writing")} · ${r.inliers} ${__("matching features")}</small></div>
			${r.status === "check" ? `<div class="cs-muted">${__("Look at this scan before trusting its cells.")}</div>` : ""}
			<div class="cs-actions"><a class="btn btn-default btn-sm" href="/app/ocr-scan/${encodeURIComponent(r.scan)}">${e(r.scan)}</a>
				<a class="btn btn-primary btn-sm" href="/app/ocr-labeling">${__("Label these cells")}</a></div>`);
	}
}
