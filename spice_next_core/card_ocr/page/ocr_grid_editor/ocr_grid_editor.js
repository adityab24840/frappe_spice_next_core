// Template and grid editor, the way Card Studio does it.
//  Step 1, the template: upload a photo, turn it a quarter turn if it lies on its side, let it level the ruled lines, check the cells it found. Drag a cell to
//  move it, drag its corner to resize, press Delete to remove it, Add to draw one, rename it and set its kind. Save template.
//  Step 2, the reader grid: say which way the card runs and how many label columns / heading rows to skip, Preview the table drawn over the card, Save grid.
const API = "spice_next_core.card_ocr.api.";
const KINDS = ["text", "number", "date", "bp", "mark"];
const E = frappe.utils.escape_html;

frappe.pages["ocr-grid-editor"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Cards"), single_column: true });
	new OcrTemplateEditor(page);
};

class OcrTemplateEditor {
	constructor(page) {
		this.page = page;
		this.S = { fields: [], sel: null, tool: "select", scale: 1, img: null, hist: [], url: null, W: 0, H: 0 };
		this.ORI = { rot: 0, str: 1, file: null };
		this.card = null; this.version = null; this.mode = null; this.base = null;     // mode: "update" (a new version of this.card) or "new" (a new template)
		this.up_for = "new";
		this.$body = $(`<div class="cs"><style>
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

			.doors { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-bottom: 16px; }
			.door { border: 1px solid var(--border-color); border-radius: 10px; padding: 16px 18px; background: var(--card-bg); }
			.door b { font-size: 11px; letter-spacing: .08em; }
			.door p { color: var(--text-muted); margin: 6px 0 10px; font-size: 13px; }
			.drop { border: 1.5px dashed var(--border-color); border-radius: 8px; padding: 18px; text-align: center; color: var(--text-muted); }
			.drop.over { border-color: var(--primary); background: var(--control-bg); }
			.te-stage { max-width: 100%; overflow: auto; border: 1px solid var(--border-color); border-radius: 8px; background: #fff; }
			.te-side { display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: 14px; }
			@media (max-width: 1000px) { .te-side { grid-template-columns: 1fr; } }
			.te-props label { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); margin-top: 8px; }
			.te-list { max-height: 260px; overflow: auto; font-size: 12px; margin-top: 8px; }
			.te-list div { cursor: pointer; padding: 2px 4px; border-radius: 4px; } .te-list div.on { background: var(--control-bg); }
			.btn.on { background: var(--primary); color: #fff; }
		</style>
		<div class="cs-eyebrow">${__("Home")}</div><div class="cs-title">${__("Cards")}</div>
		<div class="cs-lead">${__("Teach the system a handwritten health card: give it a template (a flat photo of the blank card with its cells marked), save its grid, then add filled scans.")}</div>
		<h4 style="margin:0 0 10px">${__("What do you want to do?")}</h4>
		<div class="doors">
			<div class="door"><b>${__("IDENTIFY A CARD")}</b><p>${__("Drop a photo. We find the matching template and show what was detected. Reading happens on the phone.")}</p>
				<div class="drop" data-for="identify">${__("Drop photo here or")} <button class="btn btn-default btn-sm browse">${__("Browse")}</button></div></div>
			<div class="door"><b>${__("ADD A NEW CARD TYPE")}</b><p>${__("Drop a sample card. We detect the layout, you check and approve it as a template.")}</p>
				<div class="drop" data-for="new">${__("Drop photo here or")} <button class="btn btn-default btn-sm browse">${__("Browse")}</button></div></div>
			<div class="door"><b>${__("IMPROVE A READER")}</b><p>${__("Label more cells, retrain, and see which fields are safe to ship.")}</p>
				<div class="cs-actions"><button class="btn btn-primary btn-sm go" data-p="ocr-training">${__("Open Train & Ship")}</button><button class="btn btn-default btn-sm go" data-p="ocr-labeling">${__("Label cells")}</button></div></div>
		</div>
		<div id="res"></div>
		
		<div class="cs-panel" id="orient" style="display:none"></div>
		<div class="cs-panel" id="editor" style="display:none"></div>
		<div class="cs-panel" id="tpls"></div>
		<div class="cs-panel" id="gridp" style="display:none"></div></div>`).appendTo(page.main);
		this.bind_canvas_keys();
		this.bind_doors();
		this.init();
	}

	$(id) { return this.$body.find(id); }
	call(m, a) { return frappe.call({ method: API + m, type: "POST", args: a, freeze: true, freeze_message: __("Working...") }).then((r) => r.message); }

	async init() { await this.templates(); }

	call_get(m, a) { return frappe.call({ method: API + m, type: "GET", args: a }).then((r) => r.message); }

	// ---------------------------------------------------------------- the templates and their versions
	async templates() {
		const list = await this.call_get("list_templates"), $t = this.$(`#tpls`);
		this.list_cache = list;
		if (!list.length) { $t.html(`<div class="cs-h">${__("Templates")}</div><span class="cs-muted">${__("No template yet. Use Upload template photo: a flat, straight-on photo of the blank card.")}</span>`); return; }
		$t.html(`<div class="cs-h">${__("Layouts")} <small>${__("templates in progress. Each Save makes a new version; older versions are kept, and new scans are cut with the newest version that has a grid.")}</small></div>
			<table class="cs-table"><tr><th>${__("Name")}</th><th>${__("Version")}</th><th>${__("Fields")}</th><th>${__("Saved")}</th><th></th></tr>
			${list.map((t) => t.versions.slice().reverse().map((v) => `<tr><td>${E(t.name)}</td>
				<td>v${v.version}${v.version === t.in_use ? ` <span class="cs-pill ok">${__("in use")}</span>` : ""}${v.base_version ? ` <span class="cs-muted">${__("from")} v${v.base_version}</span>` : ""}</td>
				<td>${v.cells || "—"}${v.grid ? ` · ${__("grid")} ${v.grid.rows}×${v.grid.cols}` : ""}</td><td class="cs-muted">${E(v.created)}</td>
				<td style="white-space:nowrap"><button class="btn btn-default btn-sm open" data-m="view">${__("View")}</button> <button class="btn btn-default btn-sm open" data-m="grid">${__("Grid")}</button>
					<button class="btn btn-default btn-sm dl">${__("Download")}</button> <button class="btn btn-default btn-sm open" data-m="update">${__("Update")}</button> <button class="btn btn-default btn-sm text-danger del-v">${__("Delete")}</button></td></tr>`.replace("<tr>", `<tr data-c="${E(t.name)}" data-v="${v.version}">`)).join("")).join("")}</table>`);
		$t.find(".open").on("click", (ev) => { const $r = $(ev.currentTarget).closest("tr"); this.open_version(String($r.data("c")), Number($r.data("v")), $(ev.currentTarget).data("m")); });
		$t.find(".del-v").on("click", (ev) => { const $r = $(ev.currentTarget).closest("tr"); this.delete_version(String($r.data("c")), Number($r.data("v"))); });
		$t.find(".dl").on("click", (ev) => { const $r = $(ev.currentTarget).closest("tr"); this.download(String($r.data("c")), Number($r.data("v"))); });
	}

	delete_version(card, version) {
		const v = (this.list_cache || []).find((t) => t.name === card);
		const only = v && v.versions.length === 1;
		frappe.confirm(only ? __("Delete {0} v{1}? It is the only version, so the whole card type {0} is deleted. This cannot be undone.", [card, version])
			: __("Delete {0} v{1}? Its image, cells and grid are removed and this cannot be undone. Other versions stay.", [card, version]), async () => {
			try {
				const r = await this.call("delete_template_version", { card_type: card, version });
				if (this.card === card && (r.deleted_card_type || this.version === version)) { this.$(`#editor`).hide(); this.$(`#gridp`).hide(); this.$(`#orient`).hide(); this.card = this.version = null; }
				frappe.show_alert({ message: r.deleted_card_type ? __("{0} deleted.", [card]) : __("{0} v{1} deleted.", [card, version]), indicator: "green" });
				await this.templates();
			} catch (_) { /* the server says why */ }
		});
	}

	// the version's template image, and its cells and grid as JSON
	async download(card, version) {
		const r = await this.call_get("get_template_version", { card_type: card, version });
		const save = (name, href) => { const a = document.createElement("a"); a.href = href; a.download = name; document.body.appendChild(a); a.click(); a.remove(); };
		save(`${card}-v${version}.png`, r.image);
		save(`${card}-v${version}.json`, URL.createObjectURL(new Blob([JSON.stringify({ layout: r.layout, grid: r.grid, grid_options: r.grid_opts }, null, 1)], { type: "application/json" })));
	}

	// open a saved version. view: the cells, read-only. grid: the reader-grid step only. update: edit the cells; Save makes the next version.
	async open_version(card, version, mode) {
		const r = await this.call_get("get_template_version", { card_type: card, version });
		this.card = card; this.version = version; this.base = version; this.mode = "update"; this.grid_opts = r.grid_opts; this.readonly = mode === "view";
		this.$(`#orient`).hide(); this.$(`#editor`).hide(); this.$(`#gridp`).hide();
		this.S.url = r.image; this.S.sel = null; this.S.hist = [];
		if (mode === "grid") {
			if (!r.layout) { frappe.show_alert({ message: __("That version has no cells saved (it was added with a ready-made grid). Upload a photo to make a version with cells."), indicator: "orange" }); return; }
			this.S.fields = r.layout.fields;
			await this.load_image(r.image);
			this.open_grid();
			this.$(`#gridp`)[0].scrollIntoView({ block: "nearest", behavior: "smooth" });
			return;
		}
		if (!r.layout) { frappe.show_alert({ message: __("That version has no cells saved (it was added with a ready-made grid). Upload a photo to make a version with cells."), indicator: "orange" }); return; }
		this.S.fields = r.layout.fields;
		await this.open_editor(r.image, mode === "view" ? __("View {0} v{1}", [card, version]) : __("Update {0} v{1}", [card, version]));
		this.$(`#editor`)[0].scrollIntoView({ block: "nearest", behavior: "smooth" });
	}

	load_image(src) {
		return new Promise((resolve) => {
			const im = new Image(), S = this.S;
			im.onload = () => { S.img = im; S.W = im.naturalWidth; S.H = im.naturalHeight; S.scale = Math.min(1, 1100 / im.naturalWidth); resolve(); };
			im.onerror = () => resolve();
			im.src = src;
		});
	}

	next_version(card) { const t = (this.list_cache || []).find((x) => x.name === card); return t ? Math.max(...t.versions.map((v) => v.version)) + 1 : 1; }

	// ---------------------------------------------------------------- step 1a: the photo, its orientation, what it matches
	bind_doors() {
		this.$body.find(".go").on("click", (ev) => frappe.set_route($(ev.currentTarget).data("p")));
		this.$body.find(".drop").each((_, el) => {
			const $d = $(el), kind = $d.data("for");
			$d.find(".browse").on("click", () => this.browse(kind));
			$d.on("dragover", (e) => { e.preventDefault(); $d.addClass("over"); }).on("dragleave", () => $d.removeClass("over"))
				.on("drop", async (e) => { e.preventDefault(); $d.removeClass("over"); const f = e.originalEvent.dataTransfer.files[0]; if (f) this.picked(kind, await this.push(f)); });
		});
	}

	browse(kind) {
		new frappe.ui.FileUploader({ restrictions: { allowed_file_types: ["image/*", ".heic"] }, make_attachments_public: false, on_success: (file) => this.picked(kind, file.file_url) });
	}

	// a dropped file goes up as a private file, like Browse does
	async push(file) {
		const fd = new FormData(); fd.append("file", file, file.name); fd.append("is_private", 1);
		const r = await fetch("/api/method/upload_file", { method: "POST", headers: { "X-Frappe-CSRF-Token": frappe.csrf_token }, body: fd });
		return (await r.json()).message.file_url;
	}

	picked(kind, url) {
		this.ORI = { rot: 0, str: 1, file: url };
		if (kind === "identify") this.identify(); else this.analyze();
	}

	// Identify a card: say which template the photo is, save nothing
	async identify() {
		try {
			const r = await this.call("analyze_template", { file_url: this.ORI.file, rotate: 0, straighten: 1 });
			this.$(`#editor`).hide(); this.$(`#gridp`).hide();
			const best = (r.matches || [])[0], st = r.layout.stats;
			const msg = r.verdict === "known" ? `<span class="cs-pill ok">${__("Matches")} <b>${E(best.name)} v${best.version}</b> (${__("score")} ${best.score})</span>`
				: r.verdict === "similar" ? `<span class="cs-pill warn">${__("Looks like")} <b>${E(best.name)}</b> (${__("score")} ${best.score}) ${__("but the layout differs. It will not be read with that template.")}</span>`
				: `<span class="cs-pill info">${__("New card: no existing template looks like this.")}</span>`;
			this.$(`#orient`).show().html(`<div class="cs-h">${__("Identify")}</div>${msg}
				<div class="cs-muted" style="margin-top:8px">${__("Detected {0} cells in {1} rows.", [st.cells, st.rows])} ${(r.matches || []).map((m) => `${E(m.name)} v${m.version}: ${m.score}`).join(" · ")}</div>
				<div class="cs-actions"><button class="btn btn-default btn-sm as-new">${__("Add it as a new card type")}</button></div>`);
			this.$(`#orient .as-new`).on("click", () => this.analyze());
		} catch (e) { this.$(`#orient`).show().html(`<span class="cs-pill bad">${__("failed")}</span> ${E((e && e.message) || "")}`); }
	}

	async analyze() {
		try {
			const r = await this.call("analyze_template", { file_url: this.ORI.file, rotate: this.ORI.rot, straighten: this.ORI.str });
			this.analysis = r; this.S.url = r.image; this.S.fields = r.layout.fields; this.S.sel = null; this.S.hist = [];
			this.mode = "new"; this.card = null; this.base = null; this.version = null; this.readonly = false;
			this.show_orientation(r);
			await this.open_editor(r.image, __("New template"));
			this.$(`#gridp`).hide();
		} catch (e) { this.$(`#orient`).show().html(`<span class="cs-pill bad">${__("failed")}</span> ${E((e && e.message) || "")}`); }
	}

	show_orientation(r) {
		const best = (r.matches || [])[0], st = r.layout.stats, t = r.tilt;
		let verdict;
		if (r.verdict === "known") verdict = `<div class="cs-pill ok">${__("Matches")} <b>${E(best.name)} v${best.version}</b> (${__("score")} ${best.score})</div>
			<div class="cs-actions"><button class="btn btn-default btn-sm v-update">${__("Update {0}", [E(best.name)])}</button><button class="btn btn-default btn-sm v-new">${__("Create new instead")}</button></div>`;
		else if (r.verdict === "similar") verdict = `<div class="cs-pill warn">${__("Looks like")} <b>${E(best.name)}</b> (${__("score")} ${best.score}) ${__("but the layout differs. It will not be read with that template.")}</div>
			<div class="cs-actions"><button class="btn btn-default btn-sm v-update">${__("Update {0}", [E(best.name)])}</button><button class="btn btn-primary btn-sm v-new">${__("Create new instead")}</button></div>`;
		else verdict = `<div class="cs-pill info">${__("New card: no existing template looks like this.")}${best ? ` ${__("Best score")} ${best.score} ${__("vs")} ${E(best.name)}.` : ""}</div>
			<div class="cs-actions"><button class="btn btn-primary btn-sm v-new">${__("Create new template")}</button></div>`;
		const tilt = t.straightened ? __("Levelled by {0}° (line agreement {1}%).", [(-t.tilt_deg).toFixed(1), Math.round(t.confidence * 100)]) : (t.confidence && t.confidence >= 0.3 ? __("Already level.") : (this.ORI.str ? __("No clear ruled lines to level on.") : __("Levelling is off.")));
		this.$(`#orient`).show().html(`<div class="cs-h">${__("The photo")} <small>${E(tilt)}</small></div>
			<div class="cs-actions" style="margin:0 0 8px">
				<button class="btn btn-default btn-sm turn" data-d="270">${__("Rotate ⟲")}</button><button class="btn btn-default btn-sm turn" data-d="90">${__("Rotate ⟳")}</button>
				<label style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" class="lvl" ${this.ORI.str ? "checked" : ""}> ${__("Level automatically")}</label></div>
			${verdict}
			<div class="cs-muted" style="margin-top:6px">${__("Detected {0} cells in {1} rows, {2} checkbox-like. Printed labels are not read, so cells are named r1_c1… for you to rename.", [st.cells, st.rows, st.marks])}</div>`);
		this.$(`#orient .v-update`).on("click", () => this.open_version(best.name, best.version, "update"));
		this.$(`#orient .v-new`).on("click", () => { this.mode = "new"; this.base = null; frappe.show_alert({ message: __("Editing the uploaded photo as a new template. Save asks for its name."), indicator: "blue" }); });
		this.$(`#orient .turn`).on("click", (ev) => { this.ORI.rot = (this.ORI.rot + Number($(ev.currentTarget).data("d"))) % 360; this.analyze(); });
		this.$(`#orient .lvl`).on("change", (ev) => { this.ORI.str = ev.currentTarget.checked ? 1 : 0; this.analyze(); });
	}

	// ---------------------------------------------------------------- step 1b: the cell editor (canvas)
	open_editor(src, title) {
		const $ed = this.$(`#editor`).show().html(`<div class="cs-h">${E(title)} <small id="nf"></small></div>
			<div class="cs-actions" style="margin:0 0 8px"><button class="btn btn-sm btn-default tool on" data-t="select">${__("Select")}</button><button class="btn btn-sm btn-default tool" data-t="add">${__("Add cell")}</button>
				<button class="btn btn-sm btn-default undo">${__("Undo")}</button><button class="btn btn-sm btn-default del">${__("Delete")}</button>
				<span class="cs-muted" style="align-self:center">${__("Drag to move · corner handle to resize · Delete key removes · Ctrl-Z undoes")}</span></div>
			<div class="te-side"><div class="te-stage"><canvas id="cv" tabindex="0"></canvas></div>
				<div><div class="te-props" id="props"></div><div class="te-list" id="list"></div></div></div>
			<div class="cs-actions" style="margin-top:12px"><button class="btn btn-primary btn-sm approve">${__("Save template")}</button><span id="sum" class="cs-muted" style="align-self:center"></span></div>`);
		$ed.find(".tool").on("click", (ev) => this.set_tool($(ev.currentTarget).data("t")));
		$ed.find(".undo").on("click", () => this.undo());
		$ed.find(".del").on("click", () => this.del());
		$ed.find(".approve").on("click", () => this.approve());
		if (this.readonly) { $ed.find(".tool, .undo, .del, .approve").hide(); $ed.find(".cs-muted").first().text(__("Read-only. Use Update to change the cells.")); }
		else this.bind_mouse();
		return new Promise((resolve) => {
			const im = new Image();
			im.onload = () => {
				const S = this.S; S.img = im; S.W = im.naturalWidth; S.H = im.naturalHeight; S.scale = Math.min(1, 1100 / im.naturalWidth);
				const cv = this.$(`#cv`)[0]; cv.width = Math.round(im.naturalWidth * S.scale); cv.height = Math.round(im.naturalHeight * S.scale);
				this.draw(); this.list(); this.props(); resolve();
			};
			im.onerror = () => { $ed.append(`<div class="cs-pill bad">${__("The image could not be loaded.")}</div>`); resolve(); };
			im.src = src;
		});
	}

	set_tool(t) { this.S.tool = t; this.$(`#editor .tool`).each((_, b) => $(b).toggleClass("on", $(b).data("t") === t)); }
	snap() { this.S.hist.push(JSON.stringify(this.S.fields)); if (this.S.hist.length > 100) this.S.hist.shift(); }
	undo() { if (!this.S.hist.length) return; this.S.fields = JSON.parse(this.S.hist.pop()); this.S.sel = null; this.draw(); this.list(); this.props(); }
	del() { const S = this.S; if (S.sel == null) return; this.snap(); S.fields = S.fields.filter((f) => f.id !== S.sel); S.sel = null; this.draw(); this.list(); this.props(); }
	color(k) { return k === "mark" ? "#157f3b" : ["number", "date", "bp"].includes(k) ? "#2457d6" : "#b54708"; }

	draw() {
		const S = this.S, cv = this.$(`#cv`)[0]; if (!cv || !S.img) return;
		const c = cv.getContext("2d"); c.clearRect(0, 0, cv.width, cv.height); c.drawImage(S.img, 0, 0, cv.width, cv.height);
		S.fields.forEach((f) => {
			const s = S.scale, sel = f.id === S.sel;
			c.lineWidth = sel ? 3 : 1.5; c.strokeStyle = sel ? "#e11" : this.color(f.kind); c.fillStyle = sel ? "rgba(238,17,17,.12)" : "rgba(36,87,214,.05)";
			c.fillRect(f.x * s, f.y * s, f.w * s, f.h * s); c.strokeRect(f.x * s, f.y * s, f.w * s, f.h * s);
			if (sel) { c.fillStyle = "#e11"; c.fillRect((f.x + f.w) * s - 6, (f.y + f.h) * s - 6, 10, 10); }
		});
	}

	pt(e) { const r = this.$(`#cv`)[0].getBoundingClientRect(); return { x: (e.clientX - r.left) / (r.width / this.$(`#cv`)[0].width) / this.S.scale, y: (e.clientY - r.top) / (r.height / this.$(`#cv`)[0].height) / this.S.scale }; }
	hit(p) { const F = this.S.fields; for (let i = F.length - 1; i >= 0; i--) { const f = F[i]; if (p.x >= f.x && p.x <= f.x + f.w && p.y >= f.y && p.y <= f.y + f.h) return f; } return null; }
	free_name() { const used = new Set(this.S.fields.map((f) => f.name)); let k = this.S.fields.length + 1; while (used.has("field_" + k)) k++; return "field_" + k; }

	bind_mouse() {
		const S = this.S, cv = this.$(`#cv`);
		cv.off(".te").on("mousedown.te", (e) => {
			cv[0].focus();
			const p = this.pt(e);
			if (S.tool === "add") {
				this.snap();
				const f = { id: "f" + Date.now(), name: this.free_name(), kind: "text", section: "", x: p.x, y: p.y, w: 1, h: 1, range: "", charset: "" };
				S.fields.push(f); S.sel = f.id; this.drag = { m: "new", f, sx: p.x, sy: p.y }; return;
			}
			const cur = S.fields.find((f) => f.id === S.sel);
			if (cur && Math.abs(p.x - (cur.x + cur.w)) < 10 / S.scale && Math.abs(p.y - (cur.y + cur.h)) < 10 / S.scale) { this.snap(); this.drag = { m: "size", f: cur }; return; }
			const f = this.hit(p); S.sel = f ? f.id : null;
			if (f) { this.snap(); this.drag = { m: "move", f, ox: p.x - f.x, oy: p.y - f.y }; }
			this.draw(); this.props(); this.list();
		});
		$(window).off(".te").on("mousemove.te", (e) => {
			const d = this.drag; if (!d) return;
			const p = this.pt(e), f = d.f;
			if (d.m === "move") { f.x = Math.round(p.x - d.ox); f.y = Math.round(p.y - d.oy); }
			else if (d.m === "size") { f.w = Math.max(6, Math.round(p.x - f.x)); f.h = Math.max(6, Math.round(p.y - f.y)); }
			else { f.x = Math.round(Math.min(p.x, d.sx)); f.y = Math.round(Math.min(p.y, d.sy)); f.w = Math.round(Math.abs(p.x - d.sx)); f.h = Math.round(Math.abs(p.y - d.sy)); }
			this.draw();
		}).on("mouseup.te", () => {
			const d = this.drag; if (!d) return;
			if (d.m === "new" && (d.f.w < 6 || d.f.h < 6)) { S.fields.pop(); S.sel = null; }
			this.drag = null; this.set_tool("select"); this.draw(); this.props(); this.list();
		});
	}

	bind_canvas_keys() {
		$(document).off("keydown.te").on("keydown.te", (e) => {
			if (!this.$(`#editor`).is(":visible") || ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
			if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); this.del(); }
			if ((e.ctrlKey || e.metaKey) && e.key === "z") { e.preventDefault(); this.undo(); }
		});
	}

	props() {
		const f = this.S.fields.find((x) => x.id === this.S.sel), $p = this.$(`#props`);
		if (!f) { $p.html(`<span class="cs-muted">${__("Click a cell.")}</span>`); return; }
		$p.html(`<label>${__("Name")}</label><input class="form-control input-sm p-name" value="${E(f.name)}">
			<label>${__("Kind")}</label><select class="form-control input-sm p-kind">${KINDS.map((k) => `<option ${k === f.kind ? "selected" : ""}>${k}</option>`).join("")}</select>
			<label>${__("Section")}</label><input class="form-control input-sm p-section" value="${E(f.section || "")}">
			<label>${__("Range (e.g. 30-150)")}</label><input class="form-control input-sm p-range" value="${E(f.range || "")}">
			<label>${__("Charset (e.g. 0-9.)")}</label><input class="form-control input-sm p-charset" value="${E(f.charset || "")}">
			<label>x, y, w, h</label><div class="cs-muted">${[f.x, f.y, f.w, f.h].map(Math.round).join(", ")}</div>`);
		const set = (k, v) => { f[k] = v; if (k === "kind") this.draw(); this.list(); };
		$p.find(".p-name").on("input", (e) => set("name", e.target.value));
		$p.find(".p-kind").on("change", (e) => set("kind", e.target.value));
		$p.find(".p-section").on("input", (e) => set("section", e.target.value));
		$p.find(".p-range").on("input", (e) => set("range", e.target.value));
		$p.find(".p-charset").on("input", (e) => set("charset", e.target.value));
	}

	list() {
		this.$(`#nf`).text(`${this.S.fields.length} ${__("cells")}`);
		const $l = this.$(`#list`).empty();
		this.S.fields.forEach((f) => $(`<div class="${f.id === this.S.sel ? "on" : ""}">${E(f.name)} <span class="cs-muted">${E(f.kind)}</span></div>`).appendTo($l)
			.on("click", () => { this.S.sel = f.id; this.draw(); this.props(); this.list(); }));
	}

	// Studio's editor renames repeated cell names (_2, _3) before it saves, because the server refuses duplicates
	dedupe() {
		const seen = new Set(); let n = 0;
		this.S.fields.forEach((f) => {
			f.name = String(f.name || "").trim() || "field";
			if (seen.has(f.name)) { let base = f.name, k = 2; while (seen.has(`${base}_${k}`)) k++; f.name = `${base}_${k}`; n++; }
			seen.add(f.name);
		});
		return n;
	}

	approve() {
		const S = this.S;
		if (!S.fields.length) { frappe.show_alert({ message: __("No cells to save."), indicator: "red" }); return; }
		if (this.mode === "update" && this.card) return this.save_layout(this.card, 0, "");
		const taken = new Set((this.list_cache || []).map((t) => t.name));
		const d = new frappe.ui.Dialog({
			title: __("Name this template"), fields: [
				{ fieldname: "name", fieldtype: "Data", label: __("Template name"), reqd: 1, default: this.suggest_name(), description: __("Letters, digits, _ or - (at most 40).") },
				{ fieldname: "title", fieldtype: "Data", label: __("Title (shown in lists)") }],
			primary_action_label: __("Save"), primary_action: (v) => {
				const name = String(v.name || "").replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 40);
				if (!name) return;
				if (taken.has(name)) { frappe.show_alert({ message: __("A template called {0} already exists: pick another name, or use Update on it.", [name]), indicator: "red" }); return; }
				d.hide(); this.save_layout(name, 1, v.title || "");
			},
		});
		d.show();
	}

	suggest_name() {
		const taken = new Set((this.list_cache || []).map((t) => t.name)); let k = 1, n = "new_card";
		while (taken.has(n)) n = `new_card_${++k}`;
		return n;
	}

	async save_layout(card, create, title) {
		const S = this.S, renamed = this.dedupe();
		if (renamed) { this.list(); this.props(); }
		try {
			const r = await this.call("save_layout", { card_type: card, image_url: S.url, fields: JSON.stringify(S.fields), base_version: this.base || "", create, title });
			this.card = card; this.version = r.version; this.mode = "update"; this.base = r.version; this.grid_opts = this.grid_opts || null;
			S.url = r.image;
			this.$(`#sum`).html(`<span class="cs-pill ok">${__("saved")}</span> <b>${E(card)} v${r.version}</b> · ${r.cells} ${__("cells")}${renamed ? ` · ${renamed} ${__("repeated name(s) renamed with a suffix")}` : ""} · ${__("make its grid in the next step: until then scans keep using the older version.")}`);
			await this.templates();
			this.open_grid();
		} catch (_) { /* the server says why */ }
	}

	// ---------------------------------------------------------------- step 2: the reader grid
	open_grid() {
		const o = this.grid_opts || {};
		this.$(`#gridp`).show().html(`<div class="cs-h">${__("Reader grid")} <small>${__("Turns the detected cells into the table of fields and visits a card pack needs. Say which way the card runs, then check the picture: if rows or columns are off, set how many printed label columns and heading rows to skip and how many to keep, and Preview again.")}</small></div>
			<div class="cs-actions" style="margin:0 0 8px;align-items:end">
				<label>${__("Each field is a")} <select class="form-control input-sm g-axis" style="width:auto;display:inline-block"><option value="rows">${__("row (visits are columns)")}</option><option value="columns">${__("column (visits are rows)")}</option></select></label>
				<label>${__("Label columns to skip")} <input type="number" min="0" max="20" class="form-control input-sm g-lc" style="width:80px"></label>
				<label>${__("Columns to keep (blank = all)")} <input type="number" min="1" max="60" class="form-control input-sm g-dc" style="width:80px"></label>
				<label>${__("Heading rows to skip")} <input type="number" min="0" max="20" class="form-control input-sm g-lr" style="width:80px"></label>
				<label>${__("Rows to keep (blank = all)")} <input type="number" min="1" max="99" class="form-control input-sm g-dr" style="width:80px"></label>
				<button class="btn btn-default btn-sm g-prev">${__("Preview")}</button><button class="btn btn-primary btn-sm g-save" disabled>${__("Save grid")}</button></div>
			<div id="gout"></div><div class="te-stage" style="margin-top:8px"><canvas id="gcv"></canvas></div>`);
		const $g = this.$(`#gridp`);
		$g.find(".g-axis").val(o.axis || "rows"); $g.find(".g-lc").val(o.label_cols || 0); $g.find(".g-dc").val(o.data_cols || ""); $g.find(".g-lr").val(o.label_rows || 0); $g.find(".g-dr").val(o.data_rows || "");
		$g.find(".g-prev").on("click", () => this.preview());
		$g.find(".g-save").on("click", () => this.save_grid());
		this.preview();
	}

	grid_opts_now() {
		const $g = this.$(`#gridp`), n = (c) => Number($g.find(c).val() || 0);
		return { axis: $g.find(".g-axis").val(), label_cols: n(".g-lc"), data_cols: n(".g-dc") || null, label_rows: n(".g-lr"), data_rows: n(".g-dr") || null };
	}

	async preview() {
		const card = this.card, $o = this.$(`#gout`).text(__("Working..."));
		this.$(`#gridp .g-save`).prop("disabled", true);
		try {
			const r = await this.call("preview_grid", { card_type: card, opts: JSON.stringify(this.grid_opts_now()), version: this.version || "" });
			if (r.error) { $o.html(`<span class="cs-pill bad">${E(r.error)}</span>`); return; }
			const g = r.grid, by = g.axis === "columns", nc = g.col_lines_top.length - 1, bad = r.errors.length;
			$o.html(`<div><span class="cs-pill ${bad ? "bad" : "ok"}">${bad ? __("not valid") : __("valid")}</span> <b>${by ? `${nc} ${__("field columns")} × ${g.rows.length} ${__("visit rows")}` : `${g.rows.length} ${__("field rows")} × ${nc} ${__("visit columns")}`}</b>
				${bad ? ` · ${E(r.errors.join("; "))}` : ""}</div>${r.warnings.map((w) => `<div class="cs-muted" style="color:var(--orange-600)">${E(w)}</div>`).join("")}
				<div class="cs-muted">${__("Fields")}: ${(by ? g.cols : g.rows).map(E).join(", ")}. ${by ? __("Fields named col_NN had no renamed heading cell above the visit rows") : __("Fields named row_NN had no renamed label cell left of the visit columns")}; ${__("rename cells in step 1 to name them.")}</div>`);
			this.draw_grid(g);
			this.$(`#gridp .g-save`).prop("disabled", !!bad);
		} catch (e) { $o.html(`<span class="cs-pill bad">${E((e && e.message) || "")}</span>`); }
	}

	draw_grid(g) {
		const S = this.S, cv = this.$(`#gcv`)[0], s = Math.min(1, 1100 / S.W);
		cv.width = Math.round(S.W * s); cv.height = Math.round(S.H * s);
		const c = cv.getContext("2d"); c.drawImage(S.img, 0, 0, cv.width, cv.height);
		const k = S.W / g.image_size[0], nc = g.col_lines_top.length - 1, span = g.y_ref_bot - g.y_ref_top;
		const xAt = (i, y) => (g.col_lines_top[i] + (g.col_lines_bot[i] - g.col_lines_top[i]) * (y - g.y_ref_top) / span) * k * s;
		c.lineWidth = 1.5;
		c.strokeStyle = "rgba(37,99,235,.9)"; c.beginPath();
		for (let i = 0; i <= nc; i++) { c.moveTo(xAt(i, g.y_ref_top), g.y_ref_top * k * s); c.lineTo(xAt(i, g.y_ref_bot), g.y_ref_bot * k * s); }
		c.stroke();
		c.strokeStyle = "rgba(220,38,38,.9)"; c.beginPath();
		g.row_lines_by_col.forEach((rl, ci) => rl.forEach((y) => { c.moveTo(xAt(ci, y), y * k * s); c.lineTo(xAt(ci + 1, y), y * k * s); }));
		c.stroke();
		c.font = "bold 12px system-ui"; c.fillStyle = "#b00";
		const names = g.axis === "columns" ? null : g.rows;
		if (names) g.row_lines_by_col[0].slice(0, -1).forEach((y, i) => c.fillText(names[i], 2, y * k * s + 12));
	}

	async save_grid() {
		const card = this.card;
		try {
			const r = await this.call("save_grid", { card_type: card, opts: JSON.stringify(this.grid_opts_now()), version: this.version || "" });
			this.grid_opts = r.options;
			this.$(`#gout`).prepend(`<div><span class="cs-pill ok">${__("saved")}</span> <b>${E(card)} v${r.version}</b> ${r.rows} ${__("rows")} × ${r.cols} ${__("columns")}${r.in_use === r.version ? ` · ${__("now in use for new scans")}` : ` · ${__("v{0} stays in use for new scans", [r.in_use])}`}${(r.added_fields || []).length ? ` · ${r.added_fields.length} ${__("fields added to the card type as text: set their kinds in the card type")}` : ""}</div>`);
			this.templates();
			frappe.confirm(__("Cut the scans already stored with this new grid? Labels stay where the field and visit still exist."), async () => {
				const c = await this.call("recut", { card_type: card });
				frappe.show_alert({ message: __("{0} scans re-cut, {1} cells; {2} unlabeled cells of removed fields deleted.", [c.scans, c.cells, c.removed]), indicator: "green" });
			});
		} catch (_) { /* the server says why */ }
	}
}
