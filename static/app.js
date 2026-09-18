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

// true = absteigend (bestes/größtes zuerst), false = aufsteigend
let sortDescending = true;

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
    { type: "select", options: ["ja", "nein"], get: l => l.website ? "ja" : "nein" },
    { type: "none" }, // Google Profil (immer vorhanden, kein sinnvoller Filter)
    { type: "numMin", get: l => l.icp_score || 0 },
    { type: "select", options: ["A", "B", "C"], get: l => l.icp_tier || "" },
    {
        type: "select",
        options: ["Fresha", "Treatwell", "Planity", "SumUp", "Calendly", "Booksy", "Salonized",
            "Beautinda", "Shortcuts", "Timify", "Phorest", "Terminland", "Salonkee", "Timely", "Vagaro",
            "Shore (bereits Kunde)", "ohne"],
        get: l => l.competitor_system || "ohne",
    },
    { type: "numMin", get: l => l.rating_count || 0 },
    { type: "select", options: ["ja", "nein"], get: l => l.open_now ? "ja" : "nein" },
    { type: "select", options: ["Bald eröffnend", "Neu eröffnet", "Etabliert"], get: l => l.opening_status || "Etabliert" },
    { type: "select", options: ["ja", "nein"], get: l => l.chain_flag ? "ja" : "nein" },
    { type: "text", get: l => l.pain_points },
    { type: "select", options: STATUS_OPTIONS, get: l => l.status || "Neu" },
    { type: "text", get: l => l.notes },
    { type: "text", get: l => formatFirstSeen(l.first_seen) },
    { type: "none" }, // HubSpot-Button
];

const filterState = {
    neu: { search: "", cols: {} },
    alt: { search: "", cols: {} },
    exported: { search: "", cols: {} },
};

function buildFilterRow(table, state) {
    if (!table) return;
    const thead = table.querySelector("thead");
    const tr = document.createElement("tr");
    tr.className = "filter-row";
    COLUMN_FILTERS.forEach((col, i) => {
        const th = document.createElement("th");
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
            th.appendChild(select);
        }
        tr.appendChild(th);
    });
    thead.appendChild(tr);
}

function searchableText(l) {
    return [l.name, l.address, l.phone, l.website, l.competitor_system, l.pain_points,
        l.notes, l.status, l.opening_status, l.icp_tier, l.region_query, l.category_query]
        .filter(Boolean).join(" ").toLowerCase();
}

function applyTableFilters(leads, state) {
    let rows = leads;
    if (state.search) {
        const q = state.search.toLowerCase();
        rows = rows.filter(l => searchableText(l).includes(q));
    }
    COLUMN_FILTERS.forEach((col, i) => {
        const val = state.cols[i];
        if (!val) return;
        if (col.type === "numMin") {
            const n = parseFloat(val);
            if (!isNaN(n)) rows = rows.filter(l => (col.get(l) || 0) >= n);
        } else if (col.type === "select") {
            rows = rows.filter(l => col.get(l) === val);
        } else if (col.type === "text") {
            rows = rows.filter(l => String(col.get(l) || "").toLowerCase().includes(val.toLowerCase()));
        }
    });
    return rows;
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
        <td>${website}</td>
        <td>${mapsLink}</td>
        <td><strong>${lead.icp_score != null ? lead.icp_score + " %" : ""}</strong></td>
        <td>${escapeHtml(lead.icp_tier || "")}</td>
        <td>${escapeHtml(lead.competitor_system || "—")}</td>
        <td>${lead.rating_count ?? ""}</td>
        <td>${lead.open_now ? "ja" : "nein"}</td>
        <td>${escapeHtml(lead.opening_status || "Etabliert")}${lead.opening_date ? " (" + escapeHtml(lead.opening_date) + ")" : ""}</td>
        <td>${lead.chain_flag ? "ja" : ""}</td>
        <td class="wrap">${escapeHtml(lead.pain_points || "")}</td>
        <td class="status-cell"></td>
        <td class="notes-cell"></td>
        <td>${escapeHtml(formatFirstSeen(lead.first_seen))}</td>
        <td class="hide-cell"></td>
    `;
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

function renderTable(tbodyId, countId, leads, state, useGlobalSort) {
    let rows = applyTableFilters(leads, state);
    if (useGlobalSort) {
        const sortKey = document.getElementById("sortSelect").value;
        const dir = sortDescending ? 1 : -1;
        rows = [...rows].sort((a, b) => {
            if (sortKey === "icp_score") return dir * ((b.icp_score || 0) - (a.icp_score || 0));
            if (sortKey === "rating_count") return dir * ((b.rating_count || 0) - (a.rating_count || 0));
            if (sortKey === "name") return dir * (a.name || "").localeCompare(b.name || "");
            if (sortKey === "first_seen") return dir * (b.first_seen || "").localeCompare(a.first_seen || "");
            return 0;
        });
    } else {
        rows = [...rows].sort((a, b) => (b.icp_score || 0) - (a.icp_score || 0));
    }

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
    renderTable("neuBody", "neuCount", neu, filterState.neu, false);
    renderTable("leadsBody", "leadCount", alt, filterState.alt, true);
    renderTable("exportedBody", "exportedCount", exported, filterState.exported, false);
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

function exportAs(format) {
    window.location = `/api/export?format=${format}&hot_only=0`;
    // Export blendet die exportierten Leads serverseitig aus - nach kurzer Verzoegerung neu laden
    setTimeout(async () => {
        await loadLeads();
        await loadLogs();
    }, 1500);
}

buildFilterRow(document.getElementById("neuTable"), filterState.neu);
buildFilterRow(document.getElementById("altTable"), filterState.alt);
buildFilterRow(document.getElementById("exportedTable"), filterState.exported);

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
document.getElementById("sortSelect").addEventListener("change", () => renderAll());
document.getElementById("sortDirBtn").addEventListener("click", () => {
    sortDescending = !sortDescending;
    const btn = document.getElementById("sortDirBtn");
    btn.textContent = sortDescending ? "⬇ absteigend" : "⬆ aufsteigend";
    renderAll();
});
document.getElementById("exportCsv").addEventListener("click", () => exportAs("csv"));
document.getElementById("exportXlsx").addEventListener("click", () => exportAs("xlsx"));
document.getElementById("exportHubspot").addEventListener("click", () => exportAs("hubspot"));

loadLeads();
loadLogs();
