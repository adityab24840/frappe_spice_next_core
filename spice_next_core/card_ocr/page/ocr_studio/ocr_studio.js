// Card Studio: the home page. Teach the system a handwritten health card, measure how well it reads pages it has not seen, and ship a pack to the phone.
const E = frappe.utils.escape_html;

frappe.pages["ocr-studio"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Card Studio"), single_column: true });
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
</style>`).appendTo(page.main);
	const $root = $(`<div class="cs"></div>`).appendTo(page.main);
	page.set_primary_action(__("Refresh"), () => load());
	async function load() {
		const r = (await frappe.call({ method: "spice_next_core.card_ocr.dashboard.dashboard", type: "GET" })).message;
		try { r.id_test = (await frappe.call({ method: "spice_next_core.card_ocr.api.id_test", type: "GET" })).message; } catch (_) { r.id_test = null; }
		render($root, r);
	}
	load();
};

function pct(v) { return v == null ? "—" : Math.round(v) + "%"; }

function render($root, r) {
	const t = r.tiles;
	const tile = (k, v, s, cls) => `<div class="cs-tile"><div class="k">${k}</div><div class="v ${cls || ""}">${v}</div><div class="s">${s || ""}</div></div>`;
	$root.html(`
		<div class="cs-eyebrow">${__("Home")}</div>
		<div class="cs-title">${__("Card Studio")}</div>
		<div class="cs-lead">${__("Teach the system a handwritten health card, measure how well it reads pages it has not seen, and ship a pack to the phone.")}</div>
		<div class="cs-pills">
			<span class="cs-pill ok">${__("this site only")}</span>
			<span class="cs-pill">${t.card_types} ${__("card types")}</span>
			<span class="cs-pill">${t.pack_versions} ${__("pack versions")}</span>
			${t.last_run ? `<span class="cs-pill info">${__("last run")} ${E(t.last_run)} · ${pct(t.cv_exact)} ${__("held-out")}</span>` : ""}
		</div>
		<div class="cs-tiles">
			${tile(__("Card types"), t.card_types, E(t.card_names.join(", ")))}
			${tile(__("Fields safe to ship"), `${t.shipped}<span class="of"> / ${t.fields_total}</span>`, __("passed the gate on pages the model never saw"), t.shipped ? "good" : "")}
			${tile(__("Labeled cells"), t.labeled, `${t.labeled_pages} ${__("pages")}${t.unverified ? " · " + t.unverified + " " + __("unverified machine reads") : ""}`)}
			${tile(__("Held-out exact match"), pct(t.cv_exact), __("pooled 5-fold CV, by page"))}
			${r.id_test && r.id_test.cards ? tile(__("Template ID test"), `${r.id_test.self_ok}<span class="of"> / ${r.id_test.cards}</span>`,
				E(r.id_test.note || `${r.id_test.wrongly_accepted} ${__("wrongly accepted by another card")}`), r.id_test.self_ok === r.id_test.cards ? "good" : "") : ""}
		</div>
		<div class="cs-grid2">
			<div id="registry"></div>
			<div class="cs-panel" id="steps"></div>
		</div>`);
	const $reg = $root.find("#registry");
	if (!r.registry.length) $reg.html(`<div class="cs-panel"><div class="cs-h">${__("Model registry")}</div><span class="cs-muted">${__("No card types yet.")}</span></div>`);
	r.registry.forEach((c) => $reg.append(card(c)));
	const done = r.steps.filter((s) => s.done).length;
	$root.find("#steps").html(`<div class="cs-h">${__("Getting started")} <small>${done} ${__("of")} ${r.steps.length}</small></div>
		<div class="cs-bar"><div style="width:${(100 * done) / r.steps.length}%"></div></div>` +
		r.steps.map((s) => `<div class="cs-step ${s.done ? "done" : ""}"><div class="cs-dot ${s.done ? "done" : ""}"></div>
			<div><div class="t"><a href="/app/${s.route}" style="color:inherit">${E(__(s.label))}</a></div><div class="d">${E(s.detail)}</div></div></div>`).join(""));
}

function card(c) {
	const chips = c.packs.map((p, i) => `<span class="cs-chip ${i === 0 ? "on" : ""}">v${p.version} <span class="n">${p.cv_exact != null ? Math.round(p.cv_exact) + "%" : ""}</span>
		<span class="cs-muted">${E(p.status)}</span></span>`).join("");
	const latest = c.packs[0];
	const $c = $(`<div class="cs-panel">
		<div class="cs-h">${E(c.title)} <span class="cs-tag">${E(c.card)}</span>
			<span class="cs-pill ${c.shipped ? "ok" : ""}">${c.shipped} ${__("of")} ${c.fields} ${__("fields ship")}</span></div>
		<div>${chips || `<span class="cs-muted">${__("no pack yet")}</span>`} ${c.packs.length ? `<span class="cs-muted">${c.packs.length} ${__("versions, newest first")}</span>` : ""}</div>
		<div style="margin:6px 0">
			<span class="cs-tag">${__("CRNN + CTC")}</span><span class="cs-tag">${__("48×192 gray input")}</span>
			${latest ? `<span class="cs-tag">${__("trained on")}: ${E(latest.trained_on || "?")}</span>` : ""}
			${latest ? `<span class="cs-tag">${latest.tflite ? __("TFLite reader") : __("ONNX reader only")}</span>` : ""}
			<span class="cs-tag">${c.has_template ? __("template saved") : __("no template")}</span><span class="cs-tag">${c.has_grid ? __("grid saved") : __("no grid")}</span>
		</div>
		<div class="cs-actions">
			<button class="btn btn-default btn-sm view">${__("View")}</button>
			${latest ? `<button class="btn btn-default btn-sm dl">${__("Download")}</button>` : ""}
			<button class="btn btn-primary btn-sm train">${__("Train & ship")}</button>
			<button class="btn btn-default btn-sm label">${__("Label")}</button>
		</div></div>`);
	$c.find(".view").on("click", () => frappe.set_route("Form", "OCR Card Type", c.card));
	$c.find(".dl").on("click", () => window.open(latest.pack_file));
	$c.find(".train").on("click", () => frappe.set_route("ocr-training"));
	$c.find(".label").on("click", () => frappe.set_route("ocr-labeling"));
	return $c;
}
