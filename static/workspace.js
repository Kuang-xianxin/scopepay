"use strict";
import { copy, statuses, errors, actionNames } from "/static/translations.js";
import { validateResponse } from "/static/contracts.js";
const $ = (s) => document.querySelector(s);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
let lang = localStorage.getItem("scopepay-language") || "zh";
let token = "",
  health = {},
  draft = null,
  snapshot = null,
  register = { items: [], counts: {}, total: 0 },
  busy = false,
  snapshotUnavailable = false;
let nav = "all",
  search = "",
  filter = "all",
  offset = 0,
  dirty = false,
  analysis = null;
let review = {
  reviewer: localStorage.getItem("scopepay-reviewer") || "",
  note: "",
  ack: false,
};
let routeEpoch = 0,
  queryEpoch = 0,
  searchTimer,
  decisionAction = null;
const tr = (key) => (copy[key] || [key, key])[lang === "zh" ? 0 : 1];
const labelStatus = (key) =>
  (statuses[key] || [key, key])[lang === "zh" ? 0 : 1];
const translatePair = (pair) => pair[lang === "zh" ? 0 : 1];
const icon = (name) =>
  ({
    plus: '<path d="M12 5v14M5 12h14"/>',
    search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
    trash: '<path d="M5 7h14M9 7V4h6v3M7 7l1 14h8l1-14M10 10v7M14 10v7"/>',
    file: '<path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h4"/>',
    check: '<circle cx="12" cy="12" r="9"/><path d="m7 12 3 3 7-7"/>',
    back: '<path d="m12 5-7 7 7 7M5 12h15"/>',
  })[name] || "";
const svg = (name) =>
  `<svg viewBox="0 0 24 24" aria-hidden="true">${icon(name)}</svg>`;
const money = (n, c = "USD") =>
  `${c} ${new Intl.NumberFormat(lang === "zh" ? "zh-CN" : "en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format((n || 0) / 100)}`;
const date = (s) =>
  s
    ? new Date(s).toLocaleString(lang === "zh" ? "zh-CN" : "en-GB", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
const cents = (value) =>
  /^\d{1,6}(\.\d{1,2})?$/.test(String(value))
    ? Number(String(value).split(".")[0]) * 100 +
      Number((String(value).split(".")[1] || "").padEnd(2, "0"))
    : null;
const units = (n) => ((n || 0) / 100).toFixed(2);
function localDate(value) {
  const d = new Date(value);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
function notice(message, success = false) {
  const el = $("#notice");
  el.textContent = message;
  el.className = success
    ? "success"
    : snapshot?.status === "unknown"
      ? "warning"
      : "";
  el.hidden = !message;
  if (message && !success) el.focus({ preventScroll: true });
}
async function api(path, body, method) {
  const epoch = routeEpoch;
  const controller = new AbortController();
  const deadline = setTimeout(()=>controller.abort(),110000);
  let r;
  try {
    r = await fetch(path, {
      signal:controller.signal,
      method: method || (body === undefined ? "GET" : "POST"),
      headers: {
        "content-type": "application/json",
        "x-scopepay-token": token,
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  } catch {
    clearTimeout(deadline);
    if (epoch !== routeEpoch) throw new Error('stale_request');
    throw new Error("network_unavailable");
  }
  let data;
  try {
    data = await r.json();
  } catch {
    if (epoch !== routeEpoch) throw new Error('stale_request');
    throw new Error("network_unavailable");
  } finally { clearTimeout(deadline); }
  if (epoch !== routeEpoch) throw new Error('stale_request');
  if (!r.ok) {
    const err = new Error(data.error || "invalid_input");
    err.status = r.status;
    throw err;
  }
  validateResponse(path, data);
  return data;
}
function friendly(e) {
  return translatePair(
    errors[e.message] ||
      (e.message?.startsWith("sandbox_")
        ? [
            "支付核对未通过，请保留订单并重新核对。",
            "Payment verification failed. Keep this order and reconcile again.",
          ]
        : e.message?.startsWith("model_")
          ? [
              "AI 输出未通过检查，原文已保留。可手动整理。",
              "AI output failed validation. Your source is kept; enter items manually.",
            ]
          : copy.apiUnavailable),
  );
}
function common() {
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  document.title = `ScopePay · ${tr("heading")}`;
  document
    .querySelectorAll("[data-text]")
    .forEach((e) => (e.textContent = tr(e.dataset.text)));
  $("#language").textContent = lang === "zh" ? "English" : "简体中文";
  $(".skip").textContent =
    lang === "zh" ? "跳到采购工作区" : "Skip to workspace";
  $(".sidebar nav").setAttribute("aria-label", tr("workspace"));
  $("#processor").textContent = tr(
    health.payment_mode === "sandbox" ? "sandbox" : "simulation",
  );
  document
    .querySelectorAll("[data-nav]")
    .forEach((e) => e.classList.toggle("active", e.dataset.nav === nav));
  $("#attentionCount").hidden = !!(draft || snapshot);
  $("#attentionCount").textContent = [
    "review",
    "unknown",
    "creating",
    "payment_declined",
  ].reduce((n, s) => n + (register.counts[s] || 0), 0);
  $("#breadcrumb").textContent = draft
    ? tr("editDraft")
    : snapshot
      ? tr("reviewTitle")
      : tr(
          nav === "paid"
            ? "receipts"
            : nav === "attention"
              ? "attention"
              : "purchases",
        );
}
async function run(fn, { recover = true } = {}) {
  if (busy) return;
  const epoch = routeEpoch;
  busy = true;
  document
    .querySelectorAll("[data-nav],#language")
    .forEach((b) => (b.disabled = true));
  const buttons = [...$("#view").querySelectorAll("button")];
  buttons.forEach((b) => (b.disabled = true));
  $("#view").setAttribute("aria-busy", "true");
  notice("");
  try {
    await fn();
  } catch (e) {
    if (epoch !== routeEpoch || e.message === 'stale_request') return;
    if (snapshot && recover) {
      try {
        snapshot = await api(`/api/quotes/${snapshot.quote.id}/snapshot`);
        snapshotUnavailable = false;
      } catch {
        if (epoch !== routeEpoch) return;
        snapshotUnavailable = true;
      }
      if (epoch !== routeEpoch) return;
      renderDetail();
    }
    notice(friendly(e));
  } finally {
    busy = false;
    document
      .querySelectorAll("[data-nav],#language")
      .forEach((b) => (b.disabled = false));
    $("#view").setAttribute("aria-busy", "false");
    if (draft) renderEditor();
    else if (snapshot) renderDetail();
    else renderRegister();
    if ($("#notice").hidden) {
      (
        $("#view button.primary:not(:disabled)") ||
        $("#view button:not(:disabled)")
      )?.focus({ preventScroll: true });
    }
  }
}
function href(params) {
  return "/?" + new URLSearchParams(params).toString();
}
async function go(params = {}, replace = false) {
  notice("");
  const u = href(params);
  history[replace ? "replaceState" : "pushState"]({}, "", u === "/?" ? "/" : u);
  await route();
}
function blank() {
  return {
    id: crypto.randomUUID(),
    version: 0,
    title: "",
    supplier: "",
    source: "",
    currency: "USD",
    budget_cents: 0,
    expires_at: new Date(Date.now() + 7 * 86400000).toISOString(),
    notes: "",
    items: [],
    analysis_id: null,
  };
}
function persistDraft() {
  if (!draft) return;
  try {
    localStorage.setItem(
      "scopepay-edit:" + draft.id,
      JSON.stringify({ draft, dirty }),
    );
    localStorage.setItem("scopepay-edit", JSON.stringify({ draft, dirty }));
  } catch {
    notice(
      lang === "zh"
        ? "浏览器存储已满，请保存草稿到服务器。"
        : "Browser storage is full. Save the draft to the server.",
    );
  }
}
function newDraft(sample = false) {
  draft = blank();
  analysis = null;
  if (sample) {
    draft.title =
      lang === "zh"
        ? "示例 · 工作室网站改版"
        : "Sample · Studio website refresh";
    draft.supplier =
      lang === "zh"
        ? "示例供应商 · North Studio"
        : "Sample supplier · North Studio";
    draft.source =
      lang === "zh"
        ? "改版三个网站页面，包含移动端适配。\n制作内容交接文档。\n长期维护另行报价。"
        : "Redesign three website pages, including mobile layouts.\nPrepare a content handover guide.\nOngoing maintenance is quoted separately.";
    const lines = draft.source.split("\n");
    draft.items = [
      {
        title:
          lang === "zh"
            ? "页面改版与移动适配"
            : "Page redesign & mobile layouts",
        quantity: 3,
        unit_cents: 12000,
        included: true,
        evidence_quote: lines[0],
      },
      {
        title: lang === "zh" ? "内容交接文档" : "Content handover guide",
        quantity: 1,
        unit_cents: 6000,
        included: true,
        evidence_quote: lines[1],
      },
      {
        title: lang === "zh" ? "长期维护" : "Ongoing maintenance",
        quantity: 1,
        unit_cents: 5000,
        included: false,
        evidence_quote: lines[2],
      },
    ];
    draft.budget_cents = 50000;
  } else
    draft.items = [
      {
        title: "",
        quantity: 1,
        unit_cents: 0,
        included: true,
        evidence_quote: "",
      },
    ];
  dirty = true;
  persistDraft();
  return go({ draft: draft.id });
}
async function route() {
  const epoch = ++routeEpoch;
  queryEpoch++;
  const p = new URLSearchParams(location.search);
  let cached = null;
  try { cached = JSON.parse(
    localStorage.getItem("scopepay-edit:" + p.get("draft")) ||
      localStorage.getItem("scopepay-edit") ||
      "null",
  ); } catch { /* Retain the broken local entry; server draft remains recoverable. */ }
  snapshot = null;
  draft = null;
  snapshotUnavailable = false;
  analysis = null;
  $("#view").innerHTML = `<p class="loading-label">${tr("loading")}</p>`;
  common();
  try {
    if (p.has("draft")) {
      const id = p.get("draft");
      if (cached?.draft?.id === id && cached.dirty) {
        draft = cached.draft;
        dirty = true;
      } else {
        const result = await api("/api/drafts/" + encodeURIComponent(id));
        if (epoch !== routeEpoch) return;
        draft = result;
        dirty = false;
        if (draft.quote_id) {
          return go({ quote: draft.quote_id }, true);
        }
      }
      if (epoch !== routeEpoch) return;
      renderEditor();
    } else if (p.has("quote")) {
      const result = await api(
        "/api/quotes/" + encodeURIComponent(p.get("quote")) + "/snapshot",
      );
      if (epoch !== routeEpoch) return;
      snapshot = result;
      review.ack = false;
      renderDetail();
    } else {
      await loadRegister();
    }
  } catch (e) {
    if (epoch !== routeEpoch || e.message === 'stale_request') return;
    $("#view").innerHTML =
      `<div class="empty"><h2>${tr("disconnected")}</h2><button id="routeRetry" class="primary">${tr("reconnect")}</button><button id="routeBack" class="text-button">${tr("back")}</button></div>`;
    $("#routeRetry").onclick = () => route();
    $("#routeBack").onclick = () => go();
    notice(friendly(e));
  }
}
async function loadRegister() {
  const version = ++queryEpoch;
  const result = await api(
    `/api/purchases?${new URLSearchParams({ search, status: filter === "all" ? nav : filter, offset, limit: 50 })}`,
  );
  if (version !== queryEpoch) return;
  register = result;
  renderRegister();
}
function renderRegister() {
  if (draft || snapshot) return;
  common();
  const rows = register.items
    .map(
      (r) =>
        `<tr><td><a class="purchase-title" data-open="${r.kind}" data-id="${r.id}" href="${href({ [r.kind === "draft" ? "draft" : "quote"]: r.id })}">${esc(r.title || tr("draftTitle"))}</a><span class="supplier">${esc(r.supplier || "—")}</span></td><td><span class="status ${r.status}">${labelStatus(r.status)}</span></td><td class="money">${money(r.total_cents, r.currency)}</td><td class="date-col muted small">${date(r.updated_at)}</td></tr>`,
    )
    .join("");
  $("#view").innerHTML =
    `<div class="page-heading"><div><h1>${tr(nav === "paid" ? "receipts" : nav === "attention" ? "attention" : "heading")}</h1></div><button id="newPurchase" class="primary">${tr("newPurchase")}</button></div>${localDraftLinks()}<div class="toolbar"><div class="search">${svg("search")}<input id="search" type="search" maxlength="200" aria-label="${tr("search")}" placeholder="${tr("search")}" value="${esc(search)}"></div><select id="statusFilter" aria-label="${tr("status")}"><option value="all">${tr("allStatus")}</option>${Object.keys(
      statuses,
    )
      .map(
        (s) =>
          `<option value="${s}" ${filter === s ? "selected" : ""}>${labelStatus(s)}</option>`,
      )
      .join(
        "",
      )}</select><button id="reloadList" class="secondary">${tr("reload")}</button></div><div class="panel">${rows ? `<table class="register-table"><thead><tr><th>${tr("purchase")}</th><th>${tr("status")}</th><th class="money">${tr("amount")}</th><th class="date-col">${tr("created")}</th></tr></thead><tbody>${rows}</tbody></table>` : `<div class="empty">${svg("file")}<h2>${tr(search || filter !== "all" || nav !== "all" ? "noMatches" : "noPurchases")}</h2><p>${tr(search || filter !== "all" || nav !== "all" ? "noMatchesText" : "emptyText")}</p><div class="button-row">${search || filter !== "all" || nav !== "all" ? `<button id="clearFilters" class="primary">${tr("clearFilters")}</button>` : `<button id="emptyNew" class="primary">${tr("newPurchase")}</button><button id="samplePurchase" class="secondary">${tr("sample")}</button>`}</div></div>`}</div><div class="list-footer"><span>${register.total} ${tr("count")}</span><div class="button-row">${rows ? `<button id="samplePurchase" class="text-button">${tr("sample")}</button>` : ""}${offset ? `<button id="previous" class="secondary">${tr("previous")}</button>` : ""}${offset + 50 < register.total ? `<button id="next" class="secondary">${tr("next")}</button>` : ""}</div></div>`;
  $("#newPurchase").onclick = () => newDraft();
  $("#emptyNew")?.addEventListener("click", () => newDraft());
  $("#samplePurchase")?.addEventListener("click", () => newDraft(true));
  $("#clearFilters")?.addEventListener("click", () => {
    search = "";
    filter = "all";
    nav = "all";
    offset = 0;
    run(loadRegister);
  });
  $("#reloadList").onclick = () => run(loadRegister);
  $("#search").oninput = (e) => {
    search = e.target.value;
    offset = 0;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      const version = ++queryEpoch;
      api(
        `/api/purchases?${new URLSearchParams({ search, status: filter === "all" ? nav : filter, offset, limit: 50 })}`,
      )
        .then((r) => {
          if (version !== queryEpoch || draft || snapshot) return;
          register = r;
          const pos = $("#search")?.selectionStart;
          renderRegister();
          $("#search")?.focus();
          if (pos !== null)
            try {
              $("#search").setSelectionRange(pos, pos);
            } catch {}
        })
        .catch((e) => notice(friendly(e)));
    }, 250);
  };
  $("#statusFilter").onchange = (e) => {
    filter = e.target.value;
    offset = 0;
    run(loadRegister);
  };
  $("#previous")?.addEventListener("click", () => {
    offset -= 50;
    run(loadRegister);
  });
  $("#next")?.addEventListener("click", () => {
    offset += 50;
    run(loadRegister);
  });
  document
    .querySelectorAll("[data-resume]")
    .forEach((b) => (b.onclick = () => go({ draft: b.dataset.resume })));
  document.querySelectorAll("[data-open]").forEach(
    (a) =>
      (a.onclick = (e) => {
        e.preventDefault();
        go({ [a.dataset.open === "draft" ? "draft" : "quote"]: a.dataset.id });
      }),
  );
}
function captureEditor() {
  if (!draft || !$("#purchaseTitle")) return;
  draft.title = $("#purchaseTitle").value;
  draft.supplier = $("#supplier").value;
  const src = $("#source").value;
  if (src !== draft.source && draft.analysis_id) {
    draft.analysis_id = null;
    analysis = null;
  }
  draft.source = src;
  draft.notes = $("#notes").value;
  draft.currency = $("#currency").value;
  draft.budget_input = $("#budget").value;
  draft.budget_cents = cents(draft.budget_input) || 0;
  const expires = $("#deadline").value;
  draft.expires_at = expires ? new Date(expires).toISOString() : "";
  draft.items = [...document.querySelectorAll(".edit-line")].map((row, i) => ({
    title: row.querySelector("[data-field=title]").value,
    quantity: Number(row.querySelector("[data-field=quantity]").value),
    unit_cents: cents(row.querySelector("[data-field=unit]").value) || 0,
    price_input: row.querySelector("[data-field=unit]").value,
    included: row.querySelector("[data-field=include]").checked,
    evidence_quote: draft.items[i]?.evidence_quote || "",
  }));
}
function totals() {
  const total = draft.items
    .filter((x) => x.included)
    .reduce((n, x) => n + (x.quantity * x.unit_cents || 0), 0);
  const remain = draft.budget_cents - total;
  if ($("#draftTotal"))
    $("#draftTotal").textContent = money(total, draft.currency);
  if ($("#budgetRemaining")) {
    $("#budgetRemaining").textContent = money(Math.abs(remain), draft.currency);
    $("#remainingLabel").textContent = tr(
      remain < 0 ? "overBudget" : "remaining",
    );
  }
  const meter = $("#budgetMeter");
  if (meter) {
    meter.style.width =
      Math.min(
        100,
        draft.budget_cents ? (total / draft.budget_cents) * 100 : 0,
      ) + "%";
    meter.parentElement.classList.toggle("over", remain < 0);
  }
  $("#saveState").textContent = tr(dirty ? "localChanges" : "saved");
  $("#saveState").className = "save-state" + (dirty ? " dirty" : "");
}
function renderEditor() {
  if (!draft) return;
  common();
  $("#view").innerHTML =
    `<button id="back" class="text-button back-button">${tr("back")}</button><div class="page-heading"><div><h1>${tr(draft.version ? "editDraft" : "draftTitle")}</h1><p>${tr("draftSubtitle")}</p></div></div><div id="validation" class="error-summary" tabindex="-1" role="alert" hidden></div><form id="draftForm" novalidate><div class="editor-layout"><div class="document"><section class="document-section"><h2>${tr("purchaseDetails")}</h2><div class="two-fields"><div class="field"><label for="purchaseTitle">${tr("title")}</label><input id="purchaseTitle" maxlength="160" value="${esc(draft.title)}" placeholder="${tr("titlePlaceholder")}" aria-describedby="purchaseTitle-error"><span class="field-error" id="purchaseTitle-error"></span></div><div class="field"><label for="supplier">${tr("supplier")}</label><input id="supplier" maxlength="160" value="${esc(draft.supplier)}" placeholder="${tr("supplierPlaceholder")}" aria-describedby="supplier-error"><span class="field-error" id="supplier-error"></span></div></div><details ${draft.items.length < 2 ? "open" : ""}><summary>${tr("original")}</summary><textarea id="source" rows="5" maxlength="12000" aria-label="${tr("original")}" placeholder="${tr("sourcePlaceholder")}">${esc(draft.source)}</textarea><div class="button-row source-actions"><button type="button" id="manualSplit" class="secondary">${tr("manualSplit")}</button><button type="button" id="extract" class="secondary">${tr("extract")}</button></div><p class="field-note">${tr("sourceHint")}</p></details>${analysis && (analysis.risks.length || analysis.questions.length) ? `<div class="source-review">${analysis.risks.length ? `<h3>${tr("suggestionRisks")}</h3><ul>${analysis.risks.map((r) => `<li>${esc(r.note)} — ${esc(r.evidence.quote)}</li>`).join("")}</ul>` : ""}${analysis.questions.length ? `<h3>${tr("questions")}</h3><ul>${analysis.questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>` : ""}</div>` : ""}</section><section class="document-section"><div class="section-heading"><h2>${tr("lineItems")}</h2><span class="muted small">${esc(draft.currency)}</span></div><div class="line-header"><span></span><span>${tr("item")}</span><span>${tr("qty")}</span><span>${tr("unit")}</span><span></span></div><div id="editLines">${draft.items.map((x, i) => `<div class="edit-line ${!x.included ? "line-excluded" : ""}" data-index="${i}"><div class="check-cell"><input type="checkbox" data-field="include" aria-label="${tr("include")} ${i + 1}" ${x.included ? "checked" : ""}></div><div class="line-title-cell"><input data-field="title" id="lineTitle${i}" aria-label="${tr("item")} ${i + 1}" aria-describedby="lineTitle${i}-error" maxlength="250" value="${esc(x.title)}" placeholder="${tr("itemPlaceholder")}"><span class="field-error" id="lineTitle${i}-error"></span>${x.evidence_quote ? `<span class="line-evidence">${tr("sourceEvidence")}: ${esc(x.evidence_quote)}</span>` : ""}</div><div class="line-qty"><label class="mobile-caption" for="lineQty${i}">${tr("qty")}</label><input id="lineQty${i}" data-field="quantity" aria-label="${tr("qty")} ${i + 1}" type="number" min="1" max="1000" step="1" value="${esc(x.quantity)}" aria-describedby="lineQty${i}-error"><span class="field-error" id="lineQty${i}-error"></span></div><div class="line-price"><label class="mobile-caption" for="linePrice${i}">${tr("unit")}</label><input id="linePrice${i}" data-field="unit" aria-label="${tr("unit")} ${i + 1}" inputmode="decimal" value="${esc(x.price_input ?? units(x.unit_cents))}" aria-describedby="linePrice${i}-error"><span class="field-error" id="linePrice${i}-error"></span></div><button class="icon-button line-remove" type="button" data-remove="${i}" aria-label="${tr("remove")} ${i + 1}">${svg("trash")}</button></div>`).join("")}</div><button class="add-line" id="addLine" type="button">+ ${tr("addLine")}</button></section><section class="document-section"><label for="notes">${tr("notes")}</label><textarea id="notes" rows="3" maxlength="2000" placeholder="${tr("notesPlaceholder")}">${esc(draft.notes)}</textarea></section></div><aside class="action-rail"><h2>${tr("budgetReview")}</h2><div class="field"><label for="currency">${tr("currency")}</label><select id="currency">${["USD", "EUR", "GBP"].map((c) => `<option ${draft.currency === c ? "selected" : ""}>${c}</option>`).join("")}</select></div><div class="field"><label for="budget">${tr("budget")} (${esc(draft.currency)})</label><input id="budget" inputmode="decimal" value="${esc(draft.budget_input ?? (draft.budget_cents ? units(draft.budget_cents) : ""))}" aria-describedby="budget-error budgetHelp"><span class="field-error" id="budget-error"></span><p id="budgetHelp" class="field-note">${tr("budgetHint")}</p></div><div class="field"><label for="deadline">${tr("deadline")}</label><input id="deadline" type="datetime-local" value="${draft.expires_at ? localDate(draft.expires_at) : ""}" aria-describedby="deadline-error"><span class="field-error" id="deadline-error"></span></div><div class="rail-divider"></div><span class="amount-label">${tr("quotedTotal")}</span><div class="amount-display" id="draftTotal"></div><div class="budget-row"><span id="remainingLabel"></span><strong id="budgetRemaining"></strong></div><div class="budget-bar"><span id="budgetMeter"></span></div><button type="submit" id="submitDraft" class="primary">${tr("submit")}</button><button type="button" id="saveDraft" class="secondary">${tr("saveDraft")}</button><p id="saveState" class="save-state"></p>${draft.version ? `<button id="reloadDraft" type="button" class="text-button">${tr("reloadSaved")}</button>` : ""}</aside></div></form>`;
  totals();
  $("#back").onclick = () => {
    captureEditor();
    persistDraft();
    go();
  };
  $("#draftForm").oninput = () => {
    captureEditor();
    dirty = true;
    persistDraft();
    totals();
  };
  $("#currency").onchange = () => {
    captureEditor();
    dirty = true;
    persistDraft();
    renderEditor();
  };
  $("#addLine").onclick = () => {
    captureEditor();
    if (draft.items.length >= 20) return;
    draft.items.push({
      title: "",
      quantity: 1,
      unit_cents: 0,
      included: true,
      evidence_quote: "",
    });
    dirty = true;
    persistDraft();
    renderEditor();
    $(`#lineTitle${draft.items.length - 1}`)?.focus();
  };
  document.querySelectorAll("[data-remove]").forEach(
    (b) =>
      (b.onclick = () => {
        captureEditor();
        draft.items.splice(Number(b.dataset.remove), 1);
        dirty = true;
        persistDraft();
        renderEditor();
      }),
  );
  $("#manualSplit").onclick = () => extractItems("manual");
  $("#extract").onclick = () => extractItems("model");
  $("#saveDraft").onclick = () => save(false);
  $("#draftForm").onsubmit = (e) => {
    e.preventDefault();
    save(true);
  };
  $("#reloadDraft")?.addEventListener("click", () =>
    run(
      async () => {
        draft = await api("/api/drafts/" + draft.id);
        dirty = false;
        persistDraft();
      },
      { recover: false },
    ),
  );
}
function validateDraft(submit) {
  const issues = [];
  const add = (id, key) => issues.push({ id, text: tr(key) });
  if (submit && !draft.title.trim()) add("purchaseTitle", "required");
  if (submit && !draft.supplier.trim()) add("supplier", "required");
  draft.items.forEach((x, i) => {
    if (submit && x.included && !x.title.trim())
      add("lineTitle" + i, "required");
    if (!Number.isInteger(x.quantity) || x.quantity < 1 || x.quantity > 1000)
      add("lineQty" + i, "invalidQty");
    const parsed = cents(x.price_input ?? units(x.unit_cents));
    if (
      parsed === null ||
      parsed > 10000000 ||
      (submit && x.included && parsed < 1)
    )
      add("linePrice" + i, "invalidMoney");
  });
  if (submit) {
    if (!draft.items.some((x) => x.included)) add("editLines", "atLeastOne");
    if (draft.budget_cents < 1) add("budget", "invalidMoney");
    if (
      draft.items
        .filter((x) => x.included)
        .reduce((n, x) => n + x.quantity * x.unit_cents, 0) > draft.budget_cents
    )
      add("budget", "budgetError");
    const deadline = new Date(draft.expires_at).getTime();
    if (
      !Number.isFinite(deadline) ||
      deadline <= Date.now() ||
      deadline > Date.now() + 90 * 86400000
    )
      add("deadline", "invalidDeadline");
  }
  document
    .querySelectorAll(".field-error")
    .forEach((e) => (e.textContent = ""));
  document
    .querySelectorAll("[aria-invalid]")
    .forEach((e) => e.removeAttribute("aria-invalid"));
  if (issues.length) {
    $("#validation").hidden = false;
    $("#validation").innerHTML =
      `<strong>${tr("errorTitle")}</strong><ul>${issues.map((e) => `<li><a href="#${e.id}">${esc(e.text)}</a></li>`).join("")}</ul>`;
    issues.forEach((e) => {
      const el = $("#" + e.id);
      el?.setAttribute("aria-invalid", "true");
      const err = $("#" + e.id + "-error");
      if (err) err.textContent = e.text;
    });
    $("#validation").focus();
    return false;
  }
  $("#validation").hidden = true;
  return true;
}
async function save(submit) {
  captureEditor();
  persistDraft();
  if (!validateDraft(submit)) return;
  await run(
    async () => {
      const {
        id,
        version,
        title,
        supplier,
        source,
        currency,
        budget_cents,
        expires_at,
        notes,
        items,
        analysis_id,
      } = draft;
      draft = await api(
        "/api/drafts/" + id,
        {
          expected_version: version,
          title,
          supplier,
          source,
          currency,
          budget_cents,
          expires_at,
          notes,
          analysis_id,
          items: items.map(({ price_input, ...x }) => x),
        },
        "PUT",
      );
      dirty = false;
      persistDraft();
      if (submit) {
        const q = await api("/api/drafts/" + id + "/submit", {});
        await go({ quote: q.id });
      } else notice(tr("savedNotice"), true);
    },
    { recover: false },
  );
}
async function extractItems(mode) {
  captureEditor();
  persistDraft();
  await run(
    async () => {
      const result = await api("/api/analyses", { source: draft.source, mode });
      analysis = result;
      draft.analysis_id = result.id;
      draft.items = draft.items.filter((x) => x.title.trim());
      for (const x of result.deliverables) {
        if (draft.items.length >= 20) break;
        if (draft.items.some((d) => d.evidence_quote === x.evidence.quote))
          continue;
        draft.items.push({
          title: x.title,
          quantity: 1,
          unit_cents: 0,
          included: false,
          evidence_quote: x.evidence.quote,
        });
      }
      dirty = true;
      persistDraft();
      notice(tr("added"), true);
    },
    { recover: false },
  );
}
function confirmation() {
  const q = snapshot.quote;
  return {
    fingerprint: q.fingerprint,
    expected_currency: q.currency,
    expected_total_cents: q.total_cents,
    acknowledge_scope: true,
  };
}
function renderDetail() {
  if (!snapshot) return;
  common();
  const q = snapshot.quote,
    o = snapshot.order,
    s = snapshot.status,
    r = snapshot.receipt;
  const complete = s === "paid";
  const stage = complete
    ? 3
    : [
          "awaiting_buyer",
          "capture_ready",
          "unknown",
          "creating",
          "payment_declined",
        ].includes(s)
      ? 2
      : 1;
  const budget = q.budget_cents ?? q.total_cents;
  const excluded =
    q.excluded_items ||
    snapshot.analysis.deliverables
      .filter((x) => q.excluded_deliverable_ids.includes(x.id))
      .map((x) => x.title);
  let rail = "";
  if (snapshotUnavailable)
    rail = `<div class="warning-block">${tr("disconnected")}</div><button id="reconnect" class="primary">${tr("reconnect")}</button>`;
  else if (complete)
    rail = `<div class="success-block"><strong>${tr(q.payment_mode === "simulation" ? "simulationReceipt" : "receipt")}</strong><p>${tr(q.payment_mode === "simulation" ? "simulationPaidText" : "paidText")}</p></div>${r ? `<label>${tr("reference")}</label><p class="receipt-number">${esc(r.id)}</p><label>${tr("issueAt")}</label><p class="small muted">${date(r.issued_at)}</p>` : ""}<button id="printReceipt" class="secondary">${tr("print")}</button>`;
  else if (s === "review")
    rail = `<div class="field"><label for="reviewer">${tr("reviewer")}</label><input id="reviewer" maxlength="100" value="${esc(review.reviewer)}" placeholder="${tr("reviewerPlaceholder")}"></div><div class="field"><label for="decisionNote">${tr("decisionNote")}</label><textarea id="decisionNote" rows="2" maxlength="1000">${esc(review.note)}</textarea></div><label class="ack-label"><input type="checkbox" id="ack" ${review.ack ? "checked" : ""}><span>${tr("ack")}</span></label><button id="approve" class="primary" ${!review.ack || !review.reviewer.trim() ? "disabled" : ""}>${tr("approve")}</button><button id="decline" class="text-button danger-text">${tr("decline")}</button>`;
  else if (["revoked", "expired", "declined", "payment_declined"].includes(s))
    rail = `<div class="warning-block">${tr(s === "payment_declined" ? "paymentDeclinedText" : s + "Text")}</div>${q.decision_note ? `<p class="activity-note">${esc(q.decision_note)}</p>` : ""}<button id="revise" class="primary">${tr("revise")}</button>`;
  else if (s === "unknown")
    rail = `<div class="warning-block"><strong>${tr("unknownTitle")}</strong><p>${tr(snapshot.reconciliation?.state === 'manual' ? 'manualReview' : 'unknownText')}</p></div>${snapshot.reconciliation?.state === 'manual' ? '' : `<button id="verify" class="primary">${tr("verify")}</button>`}`;
  else if (["approved", "creating"].includes(s))
    rail = `${s === "creating" ? `<div class="warning-block">${labelStatus(s)}</div>` : ""}${q.payment_mode === "simulation" ? `<details><summary>${tr("simulationOptions")}</summary><select id="scenario" aria-label="${tr("simulationOptions")}">${["normal", "response_lost", "declined"].map((x) => `<option value="${x}">${tr(x)}</option>`).join("")}</select></details>` : ""}<button id="createOrder" class="primary">${tr("createOrder")}</button><button id="revoke" class="text-button danger-text">${tr("revoke")}</button>`;
  else if (s === "awaiting_buyer")
    rail = `<p class="muted">${tr("buyerText")}</p>${q.payment_mode === "simulation" ? `<button id="simulateBuyer" class="primary">${tr("approveBuyer")}</button>` : o.approval_url ? `<a class="download-link" href="${esc(o.approval_url)}" target="_blank" rel="noopener noreferrer">${tr("approvalLink")}</a>` : ""}<button id="verify" class="secondary">${tr("verify")}</button><button id="revoke" class="text-button danger-text">${tr("revoke")}</button>`;
  else if (s === "capture_ready")
    rail = `<button id="capture" class="primary">${tr("capture")} ${money(q.total_cents, q.currency)}</button><button id="verify" class="secondary">${tr("verify")}</button><button id="revoke" class="text-button danger-text">${tr("revoke")}</button>`;
  $("#view").innerHTML =
    `<button id="back" class="text-button back-button">${tr("back")}</button><div class="page-heading"><div><h1>${tr(complete ? "receipt" : "reviewTitle")}</h1><p>${date(q.created_at)}</p></div><span class="mode-label">${tr(q.payment_mode === "simulation" ? "simulation" : "sandbox")}</span></div><ol class="stepper">${["quoteStep", "approvalStep", "paymentStep", "receiptStep"].map((k, i) => `<li class="${stage === i ? "current" : stage > i ? "done" : ""}" ${stage === i ? 'aria-current="step"' : ""}>${i + 1}. ${tr(k)}</li>`).join("")}</ol><div class="detail-layout"><div><article class="document">${complete ? `<div class="receipt-stamp">${svg("check")}<div><h2>${tr(q.payment_mode === "simulation" ? "simulationReceipt" : "receipt")}</h2><p>${tr(q.payment_mode === "simulation" ? "simulationPaidText" : "paidText")}</p></div></div>` : ""}<section class="document-section"><div class="document-title"><div><h2>${esc(q.title || q.items[0].title)}</h2><p class="muted">${esc(q.supplier || tr("legacy"))}</p></div><span class="status ${s}">${labelStatus(s)}</span></div><div class="doc-meta"><span>${tr("currency")}: ${q.currency}</span><span>${tr("validUntil")}: ${q.expires_at ? date(q.expires_at) : tr("noDeadline")}</span></div><table class="quote-table"><thead><tr><th>${tr("item")}</th><th class="qty">${tr("qty")}</th><th class="unit-col money">${tr("unit")}</th><th class="money">${tr("lineTotal")}</th></tr></thead><tbody>${q.items.map((x) => `<tr><td><strong>${esc(x.title)}</strong>${x.evidence?.quote ? `<small>${esc(x.evidence.quote)}</small>` : ""}</td><td class="qty">${x.quantity}</td><td class="unit-col money">${units(x.unit_cents)}</td><td class="money">${units(x.line_cents)}</td></tr>`).join("")}</tbody></table><div class="document-total"><span>${tr("amount")}</span><strong>${money(q.total_cents, q.currency)}</strong></div></section>${excluded.length ? `<section class="document-section"><h3>${tr("excluded")}</h3><ul class="scope-exclusions">${excluded.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></section>` : ""}${q.notes ? `<section class="document-section"><h3>${tr("notes")}</h3><p class="activity-note">${esc(q.notes)}</p></section>` : ""}${r ? `<section class="document-section print-only"><h3>${tr("reference")}</h3><p>${esc(r.id)}</p><p>${tr("issueAt")}: ${date(r.issued_at)}</p><p>${tr("orderReference")}: ${esc(r.order_id)}</p>${q.reviewer ? `<p>${tr("approvedBy")}: ${esc(q.reviewer)}</p>` : ""}</section>` : ""}<section class="document-section no-print"><details><summary>${tr("sourceView")}</summary><pre>${esc(snapshot.analysis.source || tr("noSource"))}</pre></details></section></article><section class="document no-print" id="activitySection"><h2>${tr("activity")}</h2><ol class="activity">${[
      ...snapshot.audit,
    ]
      .reverse()
      .map(
        (x) =>
          `<li><span class="activity-dot"></span><div>${esc(actionNames[x.action] ? translatePair(actionNames[x.action]) : x.action)}<small>${date(x.created)}${x.data?.reviewer ? " · " + esc(x.data.reviewer) : ""}</small>${x.data?.note ? `<p class="activity-note">${esc(x.data.note)}</p>` : ""}</div></li>`,
      )
      .join(
        "",
      )}</ol></section></div><aside class="action-rail"><span class="amount-label">${tr(q.confirmed_at ? "approvedAmount" : "approvalPending")}</span><div class="amount-display"><span class="currency">${q.currency}</span>${units(q.total_cents)}</div><div class="budget-row"><span>${tr("budget")}</span><strong>${money(budget, q.currency)}</strong></div><div class="budget-row"><span>${tr("remaining")}</span><strong>${money(budget - q.total_cents, q.currency)}</strong></div><div class="budget-bar"><span id="detailBudgetMeter"></span></div>${q.reviewer ? `<p class="small muted">${tr("approvedBy")}: ${esc(q.reviewer)}</p>` : ""}<div class="rail-divider"></div>${rail}<a id="download" class="download-link ${snapshotUnavailable ? "disabled-link" : ""}" ${snapshotUnavailable ? 'aria-disabled="true" tabindex="-1"' : ""} href="/api/quotes/${q.id}/export" download="scopepay-${q.id}.json">${tr(complete ? "downloadReceipt" : "export")}</a>${o?.order_id ? `<details><summary>${tr("orderReference")}</summary><p class="receipt-number">${esc(o.order_id)}</p></details>` : ""}</aside></div>`;
  $("#detailBudgetMeter").style.width =
    Math.min(100, (q.total_cents / budget) * 100) + "%";
  $("#activitySection").style.marginTop = "24px";
  $("#back").onclick = () => go();
  $("#reconnect")?.addEventListener("click", () => paymentAction(null));
  $("#approve")?.addEventListener("click", () =>
    paymentAction("confirm", {
      ...confirmation(),
      reviewer: review.reviewer.trim(),
      note: review.note,
    }),
  );
  $("#reviewer")?.addEventListener("input", (e) => {
    review.reviewer = e.target.value;
    localStorage.setItem("scopepay-reviewer", review.reviewer);
    $("#approve").disabled = !review.ack || !review.reviewer.trim();
  });
  $("#decisionNote")?.addEventListener(
    "input",
    (e) => (review.note = e.target.value),
  );
  $("#ack")?.addEventListener("change", (e) => {
    review.ack = e.target.checked;
    $("#approve").disabled = !review.ack || !review.reviewer.trim();
  });
  $("#decline")?.addEventListener("click", () => decision("decline"));
  $("#revoke")?.addEventListener("click", () => decision("revoke"));
  $("#revise")?.addEventListener("click", () =>
    run(async () => {
      const d = await api(`/api/quotes/${q.id}/revise`, {});
      await go({ draft: d.id });
    }),
  );
  $("#createOrder")?.addEventListener("click", () =>
    paymentAction("order", {
      ...confirmation(),
      simulation_scenario: $("#scenario")?.value || "normal",
    }),
  );
  $("#simulateBuyer")?.addEventListener("click", () =>
    paymentAction("simulate-approval", {}),
  );
  $("#capture")?.addEventListener("click", () =>
    paymentAction("capture", confirmation()),
  );
  $("#verify")?.addEventListener("click", () => paymentAction("refresh", {}));
  $("#printReceipt")?.addEventListener("click", () => window.print());
  if (snapshot.audit_truncated) {
    const more=document.createElement('button');more.className='text-button';more.textContent=tr('olderActivity');more.id='olderActivity';
    more.onclick=()=>run(async()=>{
      const previous=await api(`/api/quotes/${q.id}/audit?before=${snapshot.audit[0].seq}&limit=200`);
      // The DOM stays bounded: page older events, while export retains all up to its documented cap.
      snapshot.audit=previous;snapshot.audit_truncated=previous.length===200;
    });
    $("#activitySection").append(more);
  }
  if (busy) $("#view").querySelectorAll('button').forEach(b=>b.disabled=true);
}
async function paymentAction(action, body) {
  const key = snapshot.quote.id;
  await run(async () => {
    if (action) await api(`/api/quotes/${key}/${action}`, body);
    snapshot = await api(`/api/quotes/${key}/snapshot`);
    snapshotUnavailable = false;
    if (action === "refresh" && snapshot.status === "unknown")
      notice(tr("unresolved"));
  });
}
function decision(kind) {
  decisionAction = kind;
  $("#decisionTitle").textContent = tr(
    kind === "revoke" ? "confirmRevoke" : "decline",
  );
  $("#decisionText").textContent = tr(
    kind === "revoke" ? "revokeQuestion" : "declineQuestion",
  );
  $("#cancelDecision").textContent = tr("cancel");
  $("#commitDecision").textContent = tr(
    kind === "revoke" ? "confirmRevoke" : "decline",
  );
  $("#decisionFields").innerHTML =
    kind === "decline"
      ? `<label for="declineReviewer">${tr("reviewer")}</label><input id="declineReviewer" required maxlength="100" value="${esc(review.reviewer)}"><label for="declineNote">${tr("decisionNote")}</label><textarea id="declineNote" required maxlength="1000">${esc(review.note)}</textarea>`
      : "";
  $("#decisionDialog").showModal();
}
$("#cancelDecision").onclick = () => $("#decisionDialog").close();
$("#decisionForm").onsubmit = (e) => {
  e.preventDefault();
  const kind = decisionAction;
  let body = confirmation();
  if (kind === "decline") {
    const reviewer = $("#declineReviewer").value.trim(),
      note = $("#declineNote").value.trim();
    if (!reviewer || !note) return;
    body = { fingerprint: snapshot.quote.fingerprint, reviewer, note };
  }
  $("#decisionDialog").close();
  paymentAction(kind, body);
};
$("#language").onclick = () => {
  if (draft) {
    captureEditor();
    persistDraft();
  }
  lang = lang === "zh" ? "en" : "zh";
  localStorage.setItem("scopepay-language", lang);
  notice("");
  common();
  if (draft) renderEditor();
  else if (snapshot) renderDetail();
  else renderRegister();
};
document.querySelectorAll("[data-nav]").forEach(
  (b) =>
    (b.onclick = () => {
      if (draft) {
        captureEditor();
        persistDraft();
      }
      nav = b.dataset.nav;
      filter = "all";
      search = "";
      offset = 0;
      go();
    }),
);
window.addEventListener("popstate", () => route());
window.addEventListener("beforeunload", () => {
  if (draft) {
    captureEditor();
    persistDraft();
  }
});
async function boot() {
  common();
  try {
    const [session, h] = await Promise.all([
      api("/api/session"),
      api("/api/health"),
    ]);
    token = session.token;
    health = h;
    await route();
  } catch (e) {
    notice(friendly(e));
    $("#view").innerHTML =
      `<button id="bootRetry" class="primary">${tr("reconnect")}</button>`;
    $("#bootRetry").onclick = boot;
  }
}
boot();

function localDraftLinks() {
  const drafts = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key.startsWith("scopepay-edit:")) continue;
    try {
      const value = JSON.parse(localStorage.getItem(key));
      if (value.dirty) drafts.push(value.draft);
    } catch {}
  }
  if (!drafts.length) return "";
  return `<div class="local-drafts"><span>${lang === "zh" ? "继续未保存的草稿" : "Continue unsaved drafts"}</span>${drafts.map((d) => `<button class="text-button" data-resume="${esc(d.id)}">${esc(d.title || tr("draftTitle"))}</button>`).join("")}</div>`;
}
