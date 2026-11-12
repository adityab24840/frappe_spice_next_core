// OCR Training: start a training run on the PyTorch backend from the labels people have confirmed, and watch it.
const API = "spice_next_core.card_ocr.api.";
const LAB = "spice_next_core.card_ocr.labeling.";

frappe.pages["ocr-training"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("OCR Training"), single_column: true });
	new OcrTraining(page);
};

class OcrTraining {
	constructor(page) {
		this.page = page;
		this.card_field = page.add_field({ fieldname: "card", label: __("Card"), fieldtype: "Select", change: () => this.load() });
		this.pre_field = page.add_field({ fieldname: "pre", label: __("Starting weights"), fieldtype: "Select" });
		this.config_field = page.add_field({ fieldname: "config", label: __("Preset"), fieldtype: "Select", default: "light_lr3e-4",
			options: [{ value: "light_lr3e-4", label: __("Light augmentation, learning rate 3e-4 (default)") }, { value: "light_lr1e-4", label: __("Light augmentation, learning rate 1e-4 (slower, steadier)") }, { value: "nbaug_lr1e-4", label: __("Strong augmentation, learning rate 1e-4 (more distortion)") }] });
		this.target_field = page.add_field({ fieldname: "target", label: __("Ship target %"), fieldtype: "Float", default: 85, description: __("A field ships only if the low end of its 95% interval reaches this") });
		this.minn_field = page.add_field({ fieldname: "min_n", label: __("Min held-out cells"), fieldtype: "Int", default: 20 });
		this.epochs_field = page.add_field({ fieldname: "max_epochs", label: __("Max epochs per fold"), fieldtype: "Int", default: 300 });
		page.set_primary_action(__("Start training"), () => this.start());
		page.add_menu_item(__("OCR Settings"), () => frappe.set_route("Form", "OCR Settings"));
		this.$body = $(`<div class="cs ocr-training"></div>`).appendTo(page.main);
		$(`<div class="cs-eyebrow">${__("Reader")}</div><div class="cs-title">${__("Train & ship")}</div>`).appendTo(this.$body);
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
		this.$health = $(`<div class="cs-panel"></div>`).appendTo(this.$body);
		this.$labels = $(`<div class="cs-panel"></div>`).appendTo(this.$body);
		this.$runs = $(`<div class="cs-panel"></div>`).appendTo(this.$body);
		this.$result = $(`<div class="cs-panel" style="display:none"></div>`).appendTo(this.$body);
		this.$size = $(`<div class="cs-panel"></div>`).appendTo(this.$body);
		this.init();
	}

	async init() {
		const r = await frappe.call({ method: "frappe.client.get_list", args: { doctype: "OCR Card Type", fields: ["name", "title"], limit_page_length: 200 } });
		const cards = r.message || [];
		this.card_field.df.options = cards.map((c) => ({ value: c.name, label: c.title }));
		this.card_field.refresh();
		if (cards.length) this.card_field.set_value(cards[0].name);
		this.check_health();
		this.load_weights();
	}

	async load_weights() {
		const r = (await frappe.call({ method: API + "pretrained_list", type: "GET" })).message;
		const list = Array.isArray(r) ? r.filter((w) => w.ok) : [];
		this.pre_field.df.options = [{ value: "", label: __("Default from Settings") }].concat(list.map((w) => ({ value: w.name, label: `${w.name}${w.default ? " (default)" : ""} · ${w.images || "?"} images` })));
		this.pre_field.refresh();
	}

	async load_size() {
		const card = this.card_field.get_value();
		if (!card) return;
		const e = frappe.utils.escape_html;
		const r = (await frappe.call({ method: API + "datasize", type: "GET", args: { card_type: card } })).message;
		if (!r || r.error) { this.$size.html(`<div class="cs-h">${__("Is there enough labeled data?")}</div><span class="cs-muted">${e((r && (r.hint || r.error)) || "")}</span>`); return; }
		const v = { ship: ["ok", __("ships")], "more-cells": ["warn", __("needs more cells")], "not-accurate": ["bad", __("not accurate enough")], "no-data": ["", __("no labeled cells")] };
		this.$size.html(`<div class="cs-h">${__("Is there enough labeled data?")} <small>${__("what each field still needs · target: low end of the 95% interval at least")} ${r.target}%</small></div>
			<div class="cs-status">${r.labeled.cells} ${__("labeled cells on")} ${r.labeled.pages} ${__("pages")} · ${__("latest run")} ${e(r.latest_run || "—")} ·
				${Object.entries(r.counts || {}).map(([k, n]) => `${n} ${(v[k] || ["", k])[1]}`).join(" · ")}</div>
			<table class="cs-table"><tr><th>${__("Field")}</th><th>${__("Kind")}</th><th>${__("Held-out")}</th><th>${__("Exact")}</th><th>${__("Verdict")}</th><th>${__("What it needs")}</th></tr>
			${(r.fields || []).map((f) => `<tr><td>${e(f.field)}</td><td><span class="cs-tag">${e(f.kind)}</span></td><td>${f.k}/${f.n}</td><td>${Math.round((f.exact || 0) * 100)}%</td>
				<td><span class="cs-pill ${(v[f.verdict] || [""])[0]}">${e((v[f.verdict] || ["", f.verdict])[1])}</span></td>
				<td class="cs-muted">${f.verdict === "more-cells" && f.more ? `${f.more} ${__("more checked cells would prove it")}` : f.verdict === "not-accurate" ? __("more labels will not help: the reader itself has to get better") : ""}</td></tr>`).join("")}</table>
			${(r.history || []).length > 1 ? `<div class="cs-muted" style="margin-top:8px">${__("Runs so far")}: ${(r.history || []).map((h) => `${h.cells} ${__("cells")} → ${Math.round(h.exact * 100)}%`).join(" · ")}</div>` : ""}`);
	}

	async check_health() {
		const h = (await frappe.call({ method: API + "backend_health", type: "GET" })).message || {};
		this.$health.html(h.ok
			? `<div class="cs-h">${__("Training backend")}</div><span class="cs-pill ok">${__("reachable")}</span> ${h.busy ? `<span class="cs-pill warn">${__("busy with a run")}</span>` : ""}`
			: `<div class="cs-h">${__("Training backend")}</div><span class="cs-pill bad">${__("not reachable")}</span> <span class="text-muted">${frappe.utils.escape_html(h.why || "")}</span>
				<div class="text-muted" style="margin-top:6px">${__("Start it with the Python that has PyTorch, then set its URL and token in OCR Settings.")}</div>`);
	}

	async load() {
		const card = this.card_field.get_value();
		if (!card) return;
		const ov = (await frappe.call({ method: LAB + "overview", type: "GET", args: { card_type: card } })).message;
		const t = ov.total;
		this.$labels.html(`<div class="cs-h">${__("Labels")}</div>
			<div><b>${t.human}</b> ${__("checked by a person (these are what training uses)")} ·
			<b>${t.ai_read}</b> ${__("unverified machine reads (left out)")} · ${t.todo} ${__("still to label")}</div>
			<div class="text-muted" style="margin-top:4px">${__("Training needs several people-checked pages. A reader trained on machine reads is scored against the same guesses, so its accuracy would mean little.")}</div>`);
		this.load_runs();
		this.load_size();
	}

	async load_runs() {
		const card = this.card_field.get_value();
		const runs = (await frappe.call({
			method: "frappe.client.get_list",
			args: { doctype: "OCR Training Run", filters: { card_type: card }, fields: ["name", "status", "stage", "detail", "labels_human", "labels_ai_read", "pages", "cv_exact", "pack", "creation"], order_by: "creation desc", limit_page_length: 10 },
		})).message || [];
		const e = frappe.utils.escape_html;
		const cls = { Done: "ok", Failed: "bad", Running: "warn", Queued: "" };
		this.$runs.html(`<div class="cs-h">${__("Runs")}</div>` + (runs.length ? `<table class="cs-table"><tr><th>${__("Run")}</th><th>${__("Status")}</th><th>${__("Stage")}</th><th>${__("Labels")}</th><th>${__("CV exact")}</th><th>${__("Pack")}</th></tr>` +
			runs.map((r) => `<tr><td><a href="/app/ocr-training-run/${encodeURIComponent(r.name)}">${e(r.name)}</a></td>
				<td><span class="cs-pill ${cls[r.status] || ""}">${e(r.status)}</span></td><td>${e(r.stage || "")} <span class="text-muted">${e((r.detail || "").slice(0, 80))}</span></td>
				<td>${r.labels_human}${r.labels_ai_read ? " + " + r.labels_ai_read + " " + __("unverified") : ""} / ${r.pages} ${__("pages")}</td>
				<td>${r.cv_exact != null ? Math.round(r.cv_exact) + "%" : ""}</td><td>${r.pack ? `<a href="/app/ocr-card-pack/${encodeURIComponent(r.pack)}">${e(r.pack)}</a>` : ""}</td></tr>`).join("") + `</table>`
			: `<span class="text-muted">${__("No runs yet.")}</span>`));
		const running = runs.find((r) => r.status === "Running" || r.status === "Queued");
		const done = runs.find((r) => r.status === "Done");
		if (done) this.show_result(done.name);
		clearTimeout(this.timer);
		if (running) this.timer = setTimeout(() => this.refresh(running.name), 5000);
	}

	async refresh(run) {
		await frappe.call({ method: API + "refresh_training", type: "POST", args: { run } });
		this.load_runs();
	}

	async show_result(run) {
		const doc = (await frappe.call({ method: "frappe.client.get", args: { doctype: "OCR Training Run", name: run } })).message;
		let res = {};
		try { res = typeof doc.results === "string" ? JSON.parse(doc.results) : doc.results || {}; } catch (_) { return; }
		const e = frappe.utils.escape_html;
		const bar = (lo, hi, p) => `<span class="cs-range"><i style="left:${Math.round(lo * 100)}%;width:${Math.max(2, Math.round((hi - lo) * 100))}%"></i><b style="left:${Math.round(p * 100)}%"></b></span>
			<span class="cs-muted">${Math.round(lo * 100)}–${Math.round(hi * 100)}%</span>`;
		const rows = (res.fields || []).map((f) => {
			const p = f.n ? f.k / f.n : 0, lo = f.lo != null ? f.lo : p, hi = f.hi != null ? f.hi : p;
			return `<tr><td>${e(f.field)}</td><td>${f.k}/${f.n}</td><td>${Math.round(p * 100)}%</td><td>${bar(lo, hi, p)}</td><td>${f.cer != null ? Number(f.cer).toFixed(2) : "—"}</td>
				<td><span class="cs-pill ${f.status === "ship" ? "ok" : "warn"}">${e(f.status || "")}</span><div class="cs-muted">${e(f.reason || "")}</div></td></tr>`;
		}).join("");
		const pk = res.pack || {};
		this.$result.show().html(`
			<div class="cs-status"><span class="state">${__("DONE")}</span> ${e(doc.card_type)} · ${__("stage")} ${e(doc.stage || "")} · ${e(doc.detail || "")}</div>
			<div class="cs-bar blue"><div style="width:100%"></div></div>
			<div class="cs-panel" style="margin-bottom:12px"><b>${__("Pack written and validated")}:</b> ${e(pk.id || "")} v${pk.version || "?"} · ${__("shipped fields")}: ${(pk.shipped || []).length} ${__("of")} ${(res.fields || []).length}
				<div class="cs-muted">${doc.include_ai_read ? __("Trained with unverified machine reads: treat these numbers as unreliable.") : __("Trained on people-checked labels; held-out numbers come from pages the model never saw (pooled 5-fold CV).")}
				${res.cv_all && res.cv_all.exact != null ? " · " + __("pooled held-out exact") + " " + Math.round(res.cv_all.exact * 100) + "%" : ""}</div></div>
			<table class="cs-table"><tr><th>${__("Field")}</th><th>${__("Held-out")}</th><th>${__("Exact")}</th><th>${__("95% interval")}</th><th>CER</th><th>${__("Decision")}</th></tr>${rows}</table>`);
	}

	async start() {
		const card = this.card_field.get_value();
		if (!card) return;
		frappe.confirm(__("Start training a reader for {0} from the people-checked labels? Ship target {1}%, at least {2} held-out cells per field, at most {3} epochs per fold, preset {4}.", [frappe.utils.escape_html(card), this.target_field.get_value() || 85, this.minn_field.get_value() || 20, this.epochs_field.get_value() || 300, this.config_field.get_value() || "light_lr3e-4"]), async () => {
			try {
				await frappe.call({ method: API + "start_training", type: "POST", args: { card_type: card, pretrained: this.pre_field.get_value() || null, target: this.target_field.get_value() || 85, min_n: this.minn_field.get_value() || 20, max_epochs: this.epochs_field.get_value() || 300, config: this.config_field.get_value() || "light_lr3e-4" }, freeze: true, freeze_message: __("Sending labels to the training backend...") });
				frappe.show_alert({ message: __("Training started"), indicator: "green" });
			} catch (_) { /* the server message is already shown */ }
			this.check_health();
			this.load();
		});
	}
}
