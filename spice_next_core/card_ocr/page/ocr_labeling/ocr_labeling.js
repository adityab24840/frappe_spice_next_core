// OCR Labeling: confirm or correct what each handwritten cell says. A suggestion is never a label; a label is a person's answer.
const API = "spice_next_core.card_ocr.labeling.";
const E = frappe.utils.escape_html;

frappe.pages["ocr-labeling"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Label cells"), single_column: true });
	new OcrLabeling(page);
};

class OcrLabeling {
	constructor(page) {
		this.page = page;
		this.cards = [];
		this.card_field = page.add_field({ fieldname: "card", label: __("Card"), fieldtype: "Select", change: () => this.card_changed() });
		this.field_field = page.add_field({ fieldname: "field", label: __("Field"), fieldtype: "Select", change: () => this.load_queue() });
		this.show_field = page.add_field({
			fieldname: "show", label: __("Show"), fieldtype: "Select", default: "todo", change: () => this.load_queue(),
			options: [
				{ value: "todo", label: __("Still to label") },
				{ value: "ai-read", label: __("Machine reads to verify") },
				{ value: "done", label: __("Done by a person") },
				{ value: "disagree", label: __("Disagreements with the AI") },
				{ value: "phone", label: __("Phone corrections") },
				{ value: "all", label: __("All") },
			],
		});
		page.add_menu_item(__("Suggest for unlabeled cells"), () => this.suggest());
		this.$body = $(`<div class="cs"></div>`).appendTo(page.main);
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

			.ocr-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
			.ocr-tile { border: 1px solid var(--border-color); border-radius: 8px; padding: 10px; background: var(--card-bg); }
			.ocr-tile img { width: 100%; max-height: 120px; object-fit: contain; background: #fff; border: 1px solid var(--border-color); border-radius: 4px; }
			.ocr-meta { font-size: 12px; color: var(--text-muted); margin: 6px 0; display: flex; justify-content: space-between; }
			.ocr-chip { display: inline-block; cursor: pointer; padding: 2px 8px; border-radius: 12px; background: var(--control-bg); font-family: monospace; }
			.ocr-chip.unsure { background: var(--bg-orange); }
			.ocr-warn { color: var(--red-600); font-size: 12px; margin-top: 4px; }
			.ocr-tile.saved { opacity: .55; border-color: var(--green-500); }
			.ocr-actions { margin-top: 6px; display: flex; gap: 6px; }
		</style>`).appendTo(this.$body);
		$(`<div class="cs-eyebrow">${__("Data")}</div><div class="cs-title">${__("Label cells")}</div>`).appendTo(this.$body);
		this.$overview = $(`<div class="cs-panel"></div>`).appendTo(this.$body);
		this.$queue = $(`<div class="cs-panel" style="display:none"></div>`).appendTo(this.$body);
		this.load_cards();
	}

	call(method, args, type) {
		return frappe.call({ method: API + method, args, type: type || "GET" }).then((r) => r.message);
	}

	async load_cards() {
		this.cards = (await this.call("cards")) || [];
		this.card_field.df.options = this.cards.map((c) => ({ value: c.card_key, label: c.title }));
		this.card_field.refresh();
		if (this.cards.length) this.card_field.set_value(this.cards[0].card_key);
		else this.$overview.html(`<span class="cs-muted">${__("No card types yet. Create an OCR Card Type first.")}</span>`);
	}

	card_changed() {
		const c = this.cards.find((x) => x.card_key === this.card_field.get_value());
		if (!c) return;
		this.field_field.df.options = [{ value: "", label: __("All fields") }].concat(c.fields.map((k) => ({ value: k, label: k })));
		this.field_field.refresh();
		this.field_field.set_value("");
		this.load_overview();
	}

	async load_overview() {
		const card = this.card_field.get_value();
		if (!card) return;
		const ov = await this.call("overview", { card_type: card });
		const t = ov.total, f = ov.fields;
		const ready = t.pages >= 10;
		this.$overview.html(`
			<div class="cs-h">${__("Label a card's cells")} <small>${__("type what each cut cell says; that is what the reader is trained on")}</small></div>
			<div class="cs-status"><b>${t.human}</b> ${__("labeled cells on")} <b>${t.pages}</b> ${__("pages")} · ${t.todo} ${__("inked cells still to do")} ·
				<span class="${ready ? "cs-pill ok" : "cs-pill warn"}">${ready ? __("ready to train") : __("needs 10 labeled pages")}</span>
				${t.ai_read ? ` <span class="cs-pill warn">${t.ai_read} ${__("unverified machine reads")}</span>` : ""}</div>
			<div class="cs-actions" style="margin:0 0 10px">
				<button class="btn btn-primary btn-sm all">${__("Label everything to do")}</button>
				<button class="btn btn-default btn-sm train">${__("Open Train & ship")}</button>
				<button class="btn btn-default btn-sm suggest">${__("Suggest for unlabeled cells")}</button>
				<button class="btn btn-default btn-sm disagree">${__("Review disagreements")}</button>
				<button class="btn btn-default btn-sm phone">${__("Phone corrections")}</button>
			</div>
			<table class="cs-table"><tr><th>${__("Field")}</th><th>${__("Kind")}</th><th>${__("Inked cells")}</th><th>${__("Labeled")}</th><th>${__("Blank / unreadable")}</th><th>${__("AI right")}</th><th>${__("To do")}</th><th></th></tr>
			${Object.entries(f).map(([k, p]) => `<tr>
				<td>${E(k)}</td><td><span class="cs-tag">${E(p.kind)}</span>${p.layout !== "single" ? `<span class="cs-tag">${E(p.layout)}</span>` : ""}</td>
				<td>${p.cells}</td><td>${p.human}${p.ai_read ? ` <span class="cs-muted">+${p.ai_read}</span>` : ""}</td>
				<td>${p.blank_or_unreadable}</td>
				<td>${p.ai_checked ? `${Math.round((100 * p.ai_right) / p.ai_checked)}% <span class="cs-muted">(${p.ai_right}/${p.ai_checked})</span>` : "—"}</td>
				<td>${p.todo ? `<b>${p.todo}</b>` : `<span style="color:var(--green-600)">0</span>`}</td>
				<td style="white-space:nowrap"><button class="btn btn-xs btn-default go" data-f="${E(k)}" data-s="todo" ${p.todo ? "" : "disabled"}>${__("Label")}</button>
					<button class="btn btn-xs btn-default go" data-f="${E(k)}" data-s="done">${__("Review")}</button></td></tr>`).join("")}</table>`);
		this.$overview.find(".go").on("click", (ev) => this.open_field($(ev.currentTarget).data("f"), $(ev.currentTarget).data("s")));
		this.$overview.find(".all").on("click", () => this.open_field("", "todo"));
		this.$overview.find(".train").on("click", () => frappe.set_route("ocr-training"));
		this.$overview.find(".suggest").on("click", () => this.suggest());
		this.$overview.find(".disagree").on("click", () => this.open_field("", "disagree"));
		this.$overview.find(".phone").on("click", () => this.open_field("", "phone"));
	}

	open_field(field, show) {
		this.field_field.set_value(field);
		this.show_field.set_value(show);
		this.load_queue();
		this.$queue[0].scrollIntoView({ behavior: "smooth", block: "start" });
	}

	async suggest() {
		const card = this.card_field.get_value();
		if (!card) return;
		try {
			const r = (await frappe.call({ method: "spice_next_core.card_ocr.api.suggest", type: "POST", args: { card_type: card }, freeze: true, freeze_message: __("Reading the cells...") })).message;
			frappe.show_alert({ message: __("{0} cells read by {1}. Suggestions are never labels.", [r.read, r.source]), indicator: "green" });
			this.load_overview(); this.load_queue();
		} catch (_) { /* the server says why: usually no pack yet */ }
	}

	async load_queue() {
		const card = this.card_field.get_value();
		if (!card) return;
		const q = await this.call("queue", { card_type: card, field: this.field_field.get_value() || null, show: this.show_field.get_value() || "todo", limit: 24 });
		this.$queue.show().html(`<div class="cs-h">${__("Cells")} <small>${q.left} ${__("in this view")}${q.left > q.cells.length ? ", " + __("showing {0}", [q.cells.length]) : ""} · ${__("Enter saves and moves on")}</small></div>`);
		const $grid = $(`<div class="ocr-grid"></div>`).appendTo(this.$queue);
		if (!q.cells.length) $grid.html(`<div class="cs-muted">${__("Nothing in this view.")}</div>`);
		q.cells.forEach((c) => this.tile(c).appendTo($grid));
		$grid.find("input").first().focus();
	}

	tile(c) {
		const unsure = c.ai_confidence != null && c.ai_confidence < 0.7;
		const $t = $(`<div class="ocr-tile">
			${c.crop ? `<img src="${E(c.crop)}" alt="cell">` : `<div class="cs-muted">${__("no image")}</div>`}
			<div class="ocr-meta"><span>${E(c.field_key)} · ${E(c.visit)}</span><span>${E(c.page || "")}${c.writer ? " · " + E(c.writer) : ""}</span></div>
			<div>${c.ai_text ? `${__("Suggested")}: <span class="ocr-chip ${unsure ? "unsure" : ""}" title="${__("Click to use")}">${E(c.ai_text)}</span>
				<span class="cs-muted">${c.ai_confidence != null ? Math.round(c.ai_confidence * 100) + "%" : ""}</span>` : `<span class="cs-muted">${__("no suggestion")}</span>`}</div>
			${c.ai_note ? `<div class="ocr-note" style="font-size:12px;color:var(--orange-600,#ea580c);margin-top:4px">${E(c.ai_note)}${c.ai_suggestion ? ` <span class="ocr-chip use-sug" title="${__("Click to use")}">${E(c.ai_suggestion)}</span>` : ""}</div>` : ""}
			<input class="form-control input-sm" style="margin-top:6px" value="${E(c.note ? "" : c.label || "")}" placeholder="${__("What does it say?")}">
			<div class="ocr-warn"></div>
			<div class="ocr-actions">
				<button class="btn btn-xs btn-primary save">${__("Save")}</button>
				<button class="btn btn-xs btn-default blank">${__("Blank")}</button>
				<button class="btn btn-xs btn-default unreadable">${__("Unreadable")}</button>
				${c.how === "phone" ? `<button class="btn btn-xs btn-danger reject">${__("Reject")}</button>` : ""}
			</div>
			${c.how === "phone" ? `<div class="cs-muted" style="margin-top:4px">${__("Came from the phone app: confirm it with Save, or Reject it.")}</div>` : ""}
		</div>`);
		const $in = $t.find("input");
		const send = async (label, note, confirm) => {
			const r = await this.call("save", { cell: c.name, label, note: note || "", confirm: confirm ? 1 : 0 }, "POST");
			if (!r.saved) {
				$t.find(".ocr-warn").html(`${E(r.warning)} <a href="#" class="again">${__("Save anyway")}</a>`).find(".again").on("click", (ev) => { ev.preventDefault(); send(label, note, true); });
				return;
			}
			$t.addClass("saved").find(".ocr-warn").text("");
			$t.nextAll(".ocr-tile").first().find("input").focus();
		};
		$t.find(".ocr-chip:not(.use-sug)").on("click", () => { $in.val(c.ai_text); $in.focus(); });
		$t.find(".use-sug").on("click", () => { $in.val(c.ai_suggestion); $in.focus(); });
		$t.find(".save").on("click", () => send($in.val(), ""));
		$t.find(".blank").on("click", () => send("", "blank"));
		$t.find(".unreadable").on("click", () => send("", "unreadable"));
		$t.find(".reject").on("click", async () => { await this.call("clear", { cell: c.name }, "POST"); $t.addClass("saved"); $t.find(".ocr-warn").text(__("Rejected: back in the queue.")); });
		$in.on("keydown", (ev) => { if (ev.key === "Enter") send($in.val(), ""); });
		return $t;
	}
}
