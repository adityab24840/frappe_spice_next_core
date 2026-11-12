// Clean-up lab: one photo, aligned to a card pack, run through every photo clean-up method and read with the pack's reader.
const API = "spice_next_core.card_ocr.api.";
const E = frappe.utils.escape_html;

frappe.pages["ocr-cleanup-lab"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Clean-up lab"), single_column: true });
	const $body = $(`<div class="cs"><style>
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
		<div class="cs-eyebrow">${__("Reader")}</div><div class="cs-title">${__("Clean-up lab")}</div>
		<div class="cs-lead">${__("A phone photo differs from the flat scans a reader trained on. Upload one photo to see how each clean-up method changes what the reader reads. There is no ground truth for an uploaded photo: judge the reads against the card by eye.")}</div>
		<div id="out"></div></div>`).appendTo(page.main);
	const pack_field = page.add_field({ fieldname: "pack", label: __("Pack"), fieldtype: "Select" });
	frappe.call({ method: "frappe.client.get_list", args: { doctype: "OCR Card Pack", fields: ["name"], order_by: "creation desc", limit_page_length: 100 } }).then((r) => {
		pack_field.df.options = [{ value: "", label: __("Best matching pack") }].concat((r.message || []).map((p) => ({ value: p.name, label: p.name })));
		pack_field.refresh();
	});
	page.set_primary_action(__("Upload photo"), () => new frappe.ui.FileUploader({
		restrictions: { allowed_file_types: ["image/*"] }, make_attachments_public: false,
		on_success: (file) => run(file.file_url),
	}));
	async function run(file_url) {
		const $out = $body.find("#out").html(`<div class="cs-panel">${__("Reading with every method...")}</div>`);
		try {
			const r = (await frappe.call({ method: API + "cleanup_lab", type: "POST", args: { file_url, pack: pack_field.get_value() || null }, freeze: true, freeze_message: __("Running every clean-up method...") })).message;
			show($out, r);
		} catch (e) { $out.html(`<div class="cs-panel"><span class="cs-pill bad">${__("failed")}</span> ${E((e && e.message) || "")}</div>`); }
	}
	function show($out, r) {
		const rows = r.methods.map((m) => m.available ? `<tr><td>${E(m.label)} ${m.is_pack_default ? `<span class="cs-pill info">${__("pack default")}</span>` : ""}</td>
			<td>${m.seconds}s</td><td>${m.with_ink}</td><td>${m.read}</td><td>${m.flagged}</td><td>${m.mean_confidence != null ? Math.round(m.mean_confidence * 100) + "%" : "—"}</td>
			<td><a href="${E(m.image)}" target="_blank"><img src="${E(m.image)}" style="height:54px;border:1px solid var(--border-color);border-radius:4px"></a></td></tr>`
			: `<tr><td>${E(m.label)}</td><td colspan="6" class="cs-muted">${E(m.note || "")}</td></tr>`).join("");
		const methods = r.methods.filter((m) => m.available).map((m) => m.method);
		const dis = (r.disagreements || []).map((d) => `<tr><td>${E(d.field)}</td><td>${d.visit}</td>${methods.map((m) => `<td>${E((d.reads[m] || {}).text || "")}</td>`).join("")}</tr>`).join("");
		$out.html(`<div class="cs-panel"><div class="cs-status"><span class="state">${E(r.pack)}</span> ${r.inliers} ${__("matching features")} · ${r.covered_percent}% ${__("of the card covered by the photo")} · ${r.cells_total} ${__("cells")}</div>
			<table class="cs-table"><tr><th>${__("Method")}</th><th>${__("Time")}</th><th>${__("Cells with ink")}</th><th>${__("Read")}</th><th>${__("Flagged")}</th><th>${__("Mean confidence")}</th><th>${__("Page")}</th></tr>${rows}</table>
			<div class="cs-muted" style="margin-top:8px">${r.notes.map(E).join(" ")}</div></div>
			<div class="cs-panel"><div class="cs-h">${__("Cells the methods read differently")} <small>${r.disagreements_total}</small></div>
			${dis ? `<table class="cs-table"><tr><th>${__("Field")}</th><th>${__("Visit")}</th>${methods.map((m) => `<th>${E(m)}</th>`).join("")}</tr>${dis}</table>` : `<span class="cs-muted">${__("All methods agree on every cell.")}</span>`}</div>`);
	}
};
