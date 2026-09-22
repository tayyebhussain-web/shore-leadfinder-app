let currentLeads = [];
// Set von place_ids aus der letzten Suche/dem letzten Sync - wird komplett ersetzt bei jedem neuen Lauf
let newOnlyIds = new Set();
let toastTimer = null;

function apiKeyHeaders() {
    const box = document.getElementById("api-key-box");
    const headers = { "Content-Type": "application/json" };
    if (box && !box.classList.contains("hidden")) {
        const key = document.getElementById("apiKeyInput").value.trim();
        if (key) headers["X-Api-Key"] = key;
    }
    return headers;
}

function setStatus(msg) {
    document.getElementById("statusMsg").textContent = msg;
}

function showToast(msg) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 3000);
}

const STATUS_OPTIONS = ["Neu", "Kontaktiert", "Termin gebucht", "Nicht interessant", "Kein Fit"];
// Woher ein Lead kam. Aktuell liefert nur Google Maps API Leads; die weiteren Werte sind fuer spaeter
// vorgesehen (z.B. Treatwell-Verzeichnis, Northdata), damit der Filter schon bereitsteht, sobald es sie gibt.
const LEAD_SOURCES = ["Google Maps API", "Treatwell", "Northdata"];

// Sortierung je Tabelle (Neu und Alt haben je eine eigene Leiste). desc = absteigend (bestes/größtes zuerst).
const sortState = {
    neu: { key: "icp_score", desc: true },
    alt: { key: "icp_score", desc: true },
};
// place_ids der zuletzt angezeigten (gefilterten und sortierten) Zeilen je Tabelle: genau diese werden exportiert
const visibleIds = { neu: [], alt: [] };
const TOOLBAR_TABLES = ["neu", "alt"];

function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
}

// Wandelt den intern sortierbaren Zeitstempel ("2026-09-18 18:52:00") in "18:52 - 18-09-2026" um.
// Aeltere Eintraege ohne Uhrzeit ("2026-09-18") werden als "18-09-2026" angezeigt.
function formatFirstSeen(raw) {
    if (!raw) return "";
    const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2}))?/);
    if (!m) return raw;
    const [, y, mo, d, h, mi] = m;
    return h != null ? `${h}:${mi} - ${d}-${mo}-${y}` : `${d}-${mo}-${y}`;
}

// Eine Spalten-Konfiguration pro sichtbarer Tabellenspalte (gleiche Reihenfolge wie <th> in den 3 Tabellen).
const COLUMN_FILTERS = [
    { type: "text", get: l => l.name },
    { type: "text", get: l => l.address },
    { type: "text", get: l => l.phone },
    { type: "text", get: l => l.email },
    { type: "select", options: ["ja", "nein"], get: l => l.website ? "ja" : "nein" },
    { type: "none" }, // Google Profil (immer vorhanden, kein sinnvoller Filter)
    { type: "numMin", get: l => l.icp_score || 0 },
    { type: "select", options: ["A", "B", "C"], get: l => l.icp_tier || "" },
    {
        type: "select",
        options: ["Fresha", "Treatwell", "Planity", "SumUp", "Calendly", "Booksy", "Salonized",
            "Beautinda", "Shortcuts", "Timify", "Phorest", "Terminland", "Salonkee", "Timely", "Vagaro",
            "Studiobookr", "Doctolib", "Jameda", "Dr. Flex", "Samedi", "Clickdoc", "Doctena", "Dentolo",
            "Shore (bereits Kunde)", "ohne"],
        get: l => l.competitor_system || "ohne",
        showCounts: true, // hinter jedem Namen steht, wie viele Leads dieser Tabelle ihn haben: "Doctolib (12)"
        // Die Spalte kann mehrere Systeme enthalten ("Doctolib, Jameda"): "enthält" statt "genau gleich"
        match: (l, val) => val === "ohne"
            ? !l.competitor_system
            : (l.competitor_system || "").split(", ").includes(val),
    },
    { type: "numMin", get: l => l.rating_count || 0 },
    { type: "select", options: ["ja", "nein"], get: l => l.open_now ? "ja" : "nein" },
    { type: "select", options: ["Bald eröffnend", "Neu eröffnet", "Etabliert"], get: l => l.opening_status || "Etabliert" },
    { type: "select", options: ["ja", "nein"], get: l => l.chain_flag ? "ja" : "nein" },
    { type: "text", get: l => l.pain_points },
    { type: "select", options: STATUS_OPTIONS, get: l => l.status || "Neu" },
    { type: "text", get: l => l.notes },
    { type: "text", get: l => formatFirstSeen(l.first_seen) },
    { type: "select", options: LEAD_SOURCES, get: l => l.lead_source || "Google Maps API" },
    { type: "none" }, // HubSpot-Button
];

const filterState = {
    neu: { search: "", cols: {}, selects: {} },
    alt: { search: "", cols: {}, selects: {} },
    exported: { search: "", cols: {}, selects: {} },
};

// --- Spaltenreihenfolge (per Maus verschiebbar, gilt fuer alle drei Tabellen) ---
// Jede Zelle traegt data-col mit der Spalten-ID. Die Zellen werden immer in Standardreihenfolge erzeugt und
// danach nach columnOrder sortiert. Filter und Eingabefelder bleiben dabei erhalten, es werden nur Knoten verschoben.
const COLUMN_IDS = ["name", "address", "phone", "email", "website", "google", "score", "tier", "system", "reviews", "open",
    "opening", "chain", "pain", "status", "notes", "since", "source", "hubspot"];
const COLUMN_ORDER_KEY = "leadfinder.columnOrder";
const TABLE_IDS = ["neuTable", "altTable", "exportedTable"];

function sanitizeColumnOrder(saved) {
    const valid = Array.isArray(saved) && saved.length === COLUMN_IDS.length
        && new Set(saved).size === COLUMN_IDS.length && COLUMN_IDS.every(id => saved.includes(id));
    return valid ? saved.slice() : COLUMN_IDS.slice();
}

function loadColumnOrder() {
    try {
        return sanitizeColumnOrder(JSON.parse(localStorage.getItem(COLUMN_ORDER_KEY)));
    } catch (e) {
        return COLUMN_IDS.slice();
    }
}

function saveColumnOrder() {
    try {
        localStorage.setItem(COLUMN_ORDER_KEY, JSON.stringify(columnOrder));
    } catch (e) { /* z. B. privater Modus: Reihenfolge gilt dann nur bis zum Neuladen */ }
}

let columnOrder = loadColumnOrder();

// Neue Reihenfolge, wenn die gezogene Spalte (Kanten ghostLeft/ghostRight, folgt der Maus) an Nachbarn vorbeigeschoben
// wird. Getauscht wird, sobald ihre vordere Kante die MITTE des Nachbarn erreicht. Das haengt nur von der Breite des
// Nachbarn ab, nicht von der Breite der gezogenen Spalte (auch eine sehr breite Spalte reagiert nach kurzem Weg) und
// verhindert Hin-und-Her-Springen. Mehrere Tausche pro Mausbewegung sind moeglich. widths: {spaltenId: Breite in px}.
function orderAfterDrag(order, draggedId, widths, originLeft, ghostLeft, ghostRight) {
    let next = order.slice();
    for (let guard = 0; guard < order.length * 2; guard++) {
        const i = next.indexOf(draggedId);
        if (i < 0) return order;
        const pos = {};
        let left = originLeft;
        next.forEach(id => { pos[id] = { left, right: left + widths[id] }; left += widths[id]; });
        const rightId = next[i + 1];
        const leftId = next[i - 1];
        if (rightId !== undefined && ghostRight > (pos[rightId].left + pos[rightId].right) / 2) {
            next.splice(i, 2, rightId, draggedId);
        } else if (leftId !== undefined && ghostLeft < (pos[leftId].left + pos[leftId].right) / 2) {
            next.splice(i - 1, 2, draggedId, leftId);
        } else {
            break;
        }
    }
    return next.join() === order.join() ? order : next;
}

function applyOrderToRow(tr, order) {
    const cells = Array.from(tr.children);
    if (!cells.length || !cells.every(c => c.dataset && c.dataset.col)) return;
    const byId = {};
    cells.forEach(c => { byId[c.dataset.col] = c; });
    const wanted = order.map(id => byId[id]).filter(Boolean);
    if (wanted.length !== cells.length || wanted.every((c, i) => c === cells[i])) return;
    wanted.forEach(c => tr.appendChild(c));
}

function applyColumnOrderEverywhere() {
    for (const id of TABLE_IDS) {
        const table = document.getElementById(id);
        if (table) table.querySelectorAll("tr").forEach(tr => applyOrderToRow(tr, columnOrder));
    }
}

function markDragColumn(id, on) {
    document.querySelectorAll(`[data-col="${id}"]`).forEach(el => el.classList.toggle("col-drag-active", on));
}

function startColumnDrag(e, headerRow, id) {
    if (e.button !== 0) return;
    const startX = e.clientX;
    const headers = Array.from(headerRow.children);
    const widths = {};
    headers.forEach(h => { widths[h.dataset.col] = h.getBoundingClientRect().width; });
    const draggedHeader = headers.find(h => h.dataset.col === id);
    const grabOffset = startX - draggedHeader.getBoundingClientRect().left; // wo die Spalte angefasst wurde
    let dragging = false;
    let ghost = null;
    const onMove = (ev) => {
        if (!dragging) {
            if (Math.abs(ev.clientX - startX) < 5) return; // erst ab 5 px gilt es als Ziehen, nicht als Klick
            dragging = true;
            document.body.classList.add("col-dragging");
            markDragColumn(id, true);
            ghost = document.createElement("div");
            ghost.className = "col-drag-ghost";
            ghost.textContent = draggedHeader.textContent.trim();
            document.body.appendChild(ghost);
        }
        ghost.style.left = (ev.clientX + 14) + "px";
        ghost.style.top = (ev.clientY + 14) + "px";
        const originLeft = headerRow.children[0].getBoundingClientRect().left;
        const ghostLeft = ev.clientX - grabOffset;
        const next = orderAfterDrag(columnOrder, id, widths, originLeft, ghostLeft, ghostLeft + widths[id]);
        if (next !== columnOrder) {
            columnOrder = next;
            applyColumnOrderEverywhere();
        }
    };
    const onUp = () => {
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
        document.removeEventListener("pointercancel", onUp);
        if (dragging) {
            if (ghost) ghost.remove();
            markDragColumn(id, false);
            document.body.classList.remove("col-dragging");
            saveColumnOrder();
        }
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("pointercancel", onUp);
}

function initColumnDragging(table) {
    if (!table) return;
    const headerRow = table.querySelector("thead tr");
    Array.from(headerRow.children).forEach((th, i) => {
        th.dataset.col = COLUMN_IDS[i];
        th.classList.add("col-draggable");
        th.title = "Mit der Maus ziehen, um die Spalte zu verschieben";
        th.addEventListener("pointerdown", (e) => startColumnDrag(e, headerRow, th.dataset.col));
    });
}

function resetColumnOrder() {
    columnOrder = COLUMN_IDS.slice();
    saveColumnOrder();
    applyColumnOrderEverywhere();
    showToast("Spaltenreihenfolge zurückgesetzt");
}

function buildFilterRow(table, state) {
    if (!table) return;
    const thead = table.querySelector("thead");
    const tr = document.createElement("tr");
    tr.className = "filter-row";
    COLUMN_FILTERS.forEach((col, i) => {
        const th = document.createElement("th");
        th.dataset.col = COLUMN_IDS[i];
        if (col.type === "text") {
            const input = document.createElement("input");
            input.type = "text";
            input.className = "col-filter-input";
            input.placeholder = "Filter ...";
            input.addEventListener("input", () => { state.cols[i] = input.value; renderAll(); });
            th.appendChild(input);
        } else if (col.type === "numMin") {
            const input = document.createElement("input");
            input.type = "number";
            input.className = "col-filter-input col-filter-num";
            input.placeholder = "min";
            input.addEventListener("input", () => { state.cols[i] = input.value; renderAll(); });
            th.appendChild(input);
        } else if (col.type === "select") {
            const select = document.createElement("select");
            select.className = "col-filter-input";
            const optAll = document.createElement("option");
            optAll.value = "";
            optAll.textContent = "alle";
            select.appendChild(optAll);
            for (const opt of col.options) {
                const o = document.createElement("option");
                o.value = opt;
                o.textContent = opt;
                select.appendChild(o);
            }
            select.addEventListener("change", () => { state.cols[i] = select.value; renderAll(); });
            state.selects[i] = select;
            th.appendChild(select);
        }
        tr.appendChild(th);
    });
    thead.appendChild(tr);
}

function searchableText(l) {
    return [l.name, l.address, l.phone, l.email, l.website, l.competitor_system, l.pain_points,
        l.notes, l.status, l.opening_status, l.icp_tier, l.region_query, l.category_query, l.lead_source]
        .filter(Boolean).join(" ").toLowerCase();
}

function applyTableFilters(leads, state, skipIndex = -1) {
    let rows = leads;
    if (state.search) {
        const q = state.search.toLowerCase();
        rows = rows.filter(l => searchableText(l).includes(q));
    }
    COLUMN_FILTERS.forEach((col, i) => {
        const val = state.cols[i];
        if (!val || i === skipIndex) return;
        if (col.type === "numMin") {
            const n = parseFloat(val);
            if (!isNaN(n)) rows = rows.filter(l => (col.get(l) || 0) >= n);
        } else if (col.type === "select") {
            rows = rows.filter(l => col.match ? col.match(l, val) : col.get(l) === val);
        } else if (col.type === "text") {
            rows = rows.filter(l => String(col.get(l) || "").toLowerCase().includes(val.toLowerCase()));
        }
    });
    return rows;
}

// Schreibt hinter jede Auswahl-Option die Trefferzahl, z. B. "Doctolib (0)". Gezaehlt wird in der jeweiligen
// Tabelle unter Beruecksichtigung aller anderen aktiven Filter und der Suche (nur der eigene Filter wird ignoriert).
function updateFilterCounts(state, leads) {
    COLUMN_FILTERS.forEach((col, i) => {
        const select = state.selects[i];
        if (!col.showCounts || !select) return;
        const rows = applyTableFilters(leads, state, i);
        for (const option of select.options) {
            if (option.value) option.textContent = `${option.value} (${rows.filter(l => col.match(l, option.value)).length})`;
        }
    });
}

function buildRow(lead) {
    const tr = document.createElement("tr");
    tr.className = `tier-${lead.icp_tier || ""}`;
    const website = lead.website ? `<a href="${lead.website}" target="_blank">Link</a>` : "";
    const searchQuery = encodeURIComponent(`${lead.name || ""} ${lead.address || ""}`.trim());
    const mapsLink = searchQuery ? `<a href="https://www.google.com/search?q=${searchQuery}" target="_blank">Profil</a>` : "";

    const statusSelect = document.createElement("select");
    statusSelect.className = "inline-select";
    for (const opt of STATUS_OPTIONS) {
        const o = document.createElement("option");
        o.value = opt;
        o.textContent = opt;
        if ((lead.status || "Neu") === opt) o.selected = true;
        statusSelect.appendChild(o);
    }
    statusSelect.addEventListener("change", async () => {
        const newStatus = statusSelect.value;
        await updateLead(lead.place_id, { status: newStatus });
        lead.status = newStatus;
        showToast(`${lead.name}: Status → ${newStatus}`);
        loadLogs();
    });

    const notesInput = document.createElement("input");
    notesInput.type = "text";
    notesInput.className = "inline-input";
    notesInput.value = lead.notes || "";
    notesInput.placeholder = "Notiz ...";
    notesInput.addEventListener("blur", () => {
        if (notesInput.value !== (lead.notes || "")) {
            lead.notes = notesInput.value;
            updateLead(lead.place_id, { notes: notesInput.value });
        }
    });

    tr.innerHTML = `
        <td>${escapeHtml(lead.name || "")}</td>
        <td class="wrap">${escapeHtml(lead.address || "")}</td>
        <td>${escapeHtml(lead.phone || "")}</td>
        <td>${lead.email ? `<a href="mailto:${escapeHtml(lead.email)}">${escapeHtml(lead.email)}</a>` : ""}</td>
        <td>${website}</td>
        <td>${mapsLink}</td>
        <td><strong>${lead.icp_score != null ? lead.icp_score + " %" : ""}</strong></td>
        <td>${escapeHtml(lead.icp_tier || "")}</td>
        <td>${escapeHtml(lead.competitor_system || "—")}</td>
        <td>${lead.rating_count ?? ""}</td>
        <td>${lead.open_now ? "ja" : "nein"}</td>
        <td>${escapeHtml(lead.opening_status || "Etabliert")}${lead.opening_date ? " (" + escapeHtml(lead.opening_date) + ")" : ""}</td>
        <td>${lead.chain_count >= 2 ? "Ja (" + lead.chain_count + ")" : ""}</td>
        <td class="wrap">${escapeHtml(lead.pain_points || "")}</td>
        <td class="status-cell"></td>
        <td class="notes-cell"></td>
        <td>${escapeHtml(formatFirstSeen(lead.first_seen))}</td>
        <td>${escapeHtml(lead.lead_source || "Google Maps API")}</td>
        <td class="hide-cell"></td>
    `;
    Array.from(tr.children).forEach((td, i) => { td.dataset.col = COLUMN_IDS[i]; });
    tr.querySelector(".status-cell").appendChild(statusSelect);
    tr.querySelector(".notes-cell").appendChild(notesInput);

    const hideBtn = document.createElement("button");
    hideBtn.className = `hide-btn secondary${lead.hidden ? " is-hidden" : ""}`;
    hideBtn.textContent = lead.hidden ? "Einblenden" : "In HubSpot";
    hideBtn.title = "Als bereits kontaktiert/in HubSpot markieren und nach 'Exportiert' verschieben";
    hideBtn.addEventListener("click", async () => {
        const newHidden = !lead.hidden;
        await updateLead(lead.place_id, { hidden: newHidden });
        lead.hidden = newHidden;
        showToast(newHidden ? `${lead.name}: ausgeblendet` : `${lead.name}: eingeblendet`);
        renderAll();
        loadLogs();
    });
    tr.querySelector(".hide-cell").appendChild(hideBtn);
    return tr;
}

function sortRows(rows, cfg) {
    const dir = cfg.desc ? 1 : -1;
    return [...rows].sort((a, b) => {
        if (cfg.key === "icp_score") return dir * ((b.icp_score || 0) - (a.icp_score || 0));
        if (cfg.key === "rating_count") return dir * ((b.rating_count || 0) - (a.rating_count || 0));
        if (cfg.key === "name") return dir * (b.name || "").localeCompare(a.name || ""); // absteigend = Z bis A
        if (cfg.key === "first_seen") return dir * (b.first_seen || "").localeCompare(a.first_seen || "");
        return 0;
    });
}

// tableKey: "neu" | "alt" (haben eine Sortier-/Export-Leiste) oder null (Exportiert: fest nach Score absteigend)
function renderTable(tbodyId, countId, leads, state, tableKey) {
    updateFilterCounts(state, leads);
    let rows = applyTableFilters(leads, state);
    rows = sortRows(rows, tableKey ? sortState[tableKey] : { key: "icp_score", desc: true });
    if (tableKey) visibleIds[tableKey] = rows.map(l => l.place_id);

    const tbody = document.getElementById(tbodyId);
    tbody.innerHTML = "";
    document.getElementById(countId).textContent = `(${rows.length} von ${leads.length})`;
    for (const lead of rows) {
        tbody.appendChild(buildRow(lead));
    }
}

function renderAll() {
    const neu = [];
    const alt = [];
    const exported = [];
    for (const lead of currentLeads) {
        if (lead.hidden) exported.push(lead);
        else if (newOnlyIds.has(lead.place_id)) neu.push(lead);
        else alt.push(lead);
    }
    renderTable("neuBody", "neuCount", neu, filterState.neu, "neu");
    renderTable("leadsBody", "leadCount", alt, filterState.alt, "alt");
    renderTable("exportedBody", "exportedCount", exported, filterState.exported, null);
    applyColumnOrderEverywhere();
}

async function updateLead(placeId, changes) {
    try {
        await fetch(`/api/leads/${encodeURIComponent(placeId)}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(changes),
        });
    } catch (e) {
        setStatus("Konnte Änderung nicht speichern: " + e);
    }
}

async function loadLeads() {
    const resp = await fetch("/api/leads");
    currentLeads = await resp.json();
    renderAll();
}

function formatLogTime(ts) {
    return formatFirstSeen(ts);
}

async function loadLogs() {
    const resp = await fetch("/api/logs?limit=50");
    const logs = await resp.json();
    const container = document.getElementById("logBody");
    container.innerHTML = "";
    document.getElementById("logCount").textContent = `(${logs.length})`;
    const latestEl = document.getElementById("logLatest");
    latestEl.textContent = logs.length ? `${formatLogTime(logs[0].created_at)}: ${logs[0].description}` : "";
    for (const log of logs) {
        const div = document.createElement("div");
        div.className = "log-entry";
        div.innerHTML = `
            <span class="log-time">${formatLogTime(log.created_at)}</span>
            <span class="log-desc">${escapeHtml(log.description)}</span>
        `;
        if (log.undoable && !log.undone) {
            const btn = document.createElement("button");
            btn.className = "secondary log-undo-btn";
            btn.textContent = "Rückgängig";
            btn.addEventListener("click", () => undoLog(log.id));
            div.appendChild(btn);
        }
        container.appendChild(div);
    }
}

async function undoLog(logId) {
    try {
        const resp = await fetch(`/api/logs/${logId}/undo`, { method: "POST" });
        const data = await resp.json();
        if (!resp.ok) {
            showToast("Fehler: " + data.error);
            return;
        }
        showToast(`Rückgängig gemacht (${data.count} betroffen)`);
        await loadLeads();
        await loadLogs();
    } catch (e) {
        showToast("Netzwerkfehler: " + e);
    }
}

function getRadiusKm() {
    const sel = document.getElementById("radiusSelect").value;
    if (sel === "custom") {
        const v = parseFloat(document.getElementById("radiusCustom").value) || 0;
        return Math.min(v, 50);
    }
    return parseFloat(sel) || 0;
}

async function doSearch() {
    const region = document.getElementById("region").value.trim();
    const category = document.getElementById("category").value.trim();
    const count = parseInt(document.getElementById("count").value, 10) || 20;
    const radius_km = getRadiusKm();
    if (!region || !category) {
        setStatus("Bitte Region und Kategorie eingeben.");
        return;
    }
    setStatus("Suche läuft ...");
    document.getElementById("searchBtn").disabled = true;
    try {
        const resp = await fetch("/api/search", {
            method: "POST",
            headers: apiKeyHeaders(),
            body: JSON.stringify({ region, category, count, radius_km }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            setStatus("Fehler: " + data.error);
            showToast("Fehler: " + data.error);
            return;
        }
        let msg = `${data.found} Treffer von Google, ${data.new} neu zur DB hinzugefügt.`;
        if (data.errors && data.errors.length) msg += ` (${data.errors.length} Fehler, siehe Konsole)`;
        if (data.errors && data.errors.length) console.warn(data.errors);
        setStatus(msg);
        showToast(msg);
        newOnlyIds = new Set(data.new_place_ids);
        await loadLeads();
        await loadLogs();
    } catch (e) {
        setStatus("Netzwerkfehler: " + e);
    } finally {
        document.getElementById("searchBtn").disabled = false;
    }
}

async function doSync() {
    setStatus("Sync läuft — prüft alle gespeicherten Suchen erneut auf neue Läden ...");
    document.getElementById("syncBtn").disabled = true;
    try {
        const resp = await fetch("/api/sync", { method: "POST", headers: apiKeyHeaders() });
        const data = await resp.json();
        if (!resp.ok) {
            setStatus("Fehler: " + data.error);
            showToast("Fehler: " + data.error);
            return;
        }
        let msg = `Sync fertig: ${data.synced_searches} gespeicherte Suchen geprüft, ${data.new} neue Leads gefunden.`;
        if (data.errors && data.errors.length) msg += ` (${data.errors.length} Fehler, siehe Konsole)`;
        if (data.errors) console.warn(data.errors);
        setStatus(msg);
        showToast(msg);
        newOnlyIds = new Set(data.new_place_ids);
        await loadLeads();
        await loadLogs();
    } catch (e) {
        setStatus("Netzwerkfehler: " + e);
    } finally {
        document.getElementById("syncBtn").disabled = false;
    }
}

async function doHideBefore() {
    const date = document.getElementById("hideBeforeDate").value;
    if (!date) {
        setStatus("Bitte ein Datum auswählen.");
        return;
    }
    if (!confirm(`Alle Leads, die am oder vor dem ${date} zuerst gefunden wurden, ausblenden?`)) return;
    try {
        const resp = await fetch("/api/leads/hide-before", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ date }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            setStatus("Fehler: " + data.error);
            showToast("Fehler: " + data.error);
            return;
        }
        setStatus(`${data.hidden} Leads ausgeblendet.`);
        showToast(`${data.hidden} Leads ausgeblendet.`);
        await loadLeads();
        await loadLogs();
    } catch (e) {
        setStatus("Netzwerkfehler: " + e);
    }
}

async function doRecheck() {
    if (!confirm("Website aller Leads erneut lesen und die Spalte 'System' sowie den Score aktualisieren? "
        + "Das dauert etwa eine Minute und ist im Aktivitäts-Log rückgängig machbar.")) return;
    const btn = document.getElementById("recheckBtn");
    btn.disabled = true;
    setStatus("Erkennung läuft — liest die Websites aller Leads ...");
    try {
        const resp = await fetch("/api/recheck", { method: "POST" });
        const data = await resp.json();
        if (!resp.ok) {
            setStatus("Fehler: " + (data.error || resp.status));
            showToast("Fehler: " + (data.error || resp.status));
            return;
        }
        const msg = `${data.changed} von ${data.checked} Leads aktualisiert (${data.unreadable} Websites nicht lesbar).`;
        setStatus(msg);
        showToast(msg);
        await loadLeads();
        await loadLogs();
    } catch (e) {
        setStatus("Netzwerkfehler: " + e);
    } finally {
        btn.disabled = false;
    }
}

// Exportiert genau die Leads, die in der Tabelle gerade sichtbar sind (mit deren Suche, Filtern und Sortierung).
// Ein unsichtbares Formular per POST loest den Download aus, ohne dass die Seite verlassen wird.
function exportTable(tableKey, format) {
    const ids = visibleIds[tableKey] || [];
    if (!ids.length) {
        showToast("Keine Leads zum Exportieren in dieser Tabelle.");
        return;
    }
    const form = document.createElement("form");
    form.method = "POST";
    form.action = "/api/export";
    form.style.display = "none";
    for (const [name, value] of [["format", format], ["ids", ids.join(",")]]) {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = name;
        input.value = value;
        form.appendChild(input);
    }
    document.body.appendChild(form);
    form.submit();
    form.remove();
    // Export blendet die exportierten Leads serverseitig aus - nach kurzer Verzoegerung neu laden
    setTimeout(async () => {
        await loadLeads();
        await loadLogs();
    }, 1500);
}

buildFilterRow(document.getElementById("neuTable"), filterState.neu);
buildFilterRow(document.getElementById("altTable"), filterState.alt);
buildFilterRow(document.getElementById("exportedTable"), filterState.exported);
TABLE_IDS.forEach(id => initColumnDragging(document.getElementById(id)));
applyColumnOrderEverywhere();

document.getElementById("neuSearch").addEventListener("input", (e) => {
    filterState.neu.search = e.target.value;
    renderAll();
});
document.getElementById("altSearch").addEventListener("input", (e) => {
    filterState.alt.search = e.target.value;
    renderAll();
});
document.getElementById("exportedSearch").addEventListener("input", (e) => {
    filterState.exported.search = e.target.value;
    renderAll();
});

document.getElementById("radiusSelect").addEventListener("change", (e) => {
    document.getElementById("radiusCustom").classList.toggle("hidden", e.target.value !== "custom");
});
document.getElementById("searchBtn").addEventListener("click", doSearch);
document.getElementById("syncBtn").addEventListener("click", doSync);
document.getElementById("hideBeforeBtn").addEventListener("click", doHideBefore);
document.getElementById("recheckBtn").addEventListener("click", doRecheck);
// Sortier-, Spalten- und Export-Leiste: je Tabelle dieselben Knoepfe (IDs mit Praefix neu/alt)
TOOLBAR_TABLES.forEach(key => {
    const select = document.getElementById(key + "SortSelect");
    const dirBtn = document.getElementById(key + "SortDirBtn");
    select.addEventListener("change", () => {
        sortState[key].key = select.value;
        renderAll();
    });
    dirBtn.addEventListener("click", () => {
        sortState[key].desc = !sortState[key].desc;
        dirBtn.textContent = sortState[key].desc ? "⬇ absteigend" : "⬆ aufsteigend";
        renderAll();
    });
    document.getElementById(key + "ResetColumnsBtn").addEventListener("click", resetColumnOrder);
    document.getElementById(key + "ExportCsv").addEventListener("click", () => exportTable(key, "csv"));
    document.getElementById(key + "ExportXlsx").addEventListener("click", () => exportTable(key, "xlsx"));
    document.getElementById(key + "ExportHubspot").addEventListener("click", () => exportTable(key, "hubspot"));
});

loadLeads();
loadLogs();
