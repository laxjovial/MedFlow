/* MedFlow web client — talks to the same API the desktop app's services power. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  token: null,
  user: null,
  patients: [],
  currentPatient: null,
};

/* ------------------------------------------------------------------ api */

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(`/api${path}`, { ...options, headers });
  if (res.status === 401 && state.token) {
    logout();
    throw new Error("Session expired — sign in again.");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body.error || body.detail || {};
    const message = typeof detail === "string"
      ? detail
      : (detail.message || JSON.stringify(detail));
    const err = new Error(message);
    err.fields = detail.fields;
    err.status = res.status;
    throw err;
  }
  return body;
}

/* ------------------------------------------------------------------ auth */

function logout() {
  state.token = null;
  state.user = null;
  localStorage.removeItem("medflow.session");
  localStorage.removeItem("medflow.remember");
  $("#app-view").classList.add("hidden");
  $("#login-gate").classList.remove("hidden");
}

async function login(username, password, remember = false) {
  const data = await api("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password, remember }),
  });
  state.token = data.token;
  state.user = data.user;
  localStorage.setItem("medflow.session",
    JSON.stringify({ token: data.token, user: data.user }));
  enterApp();
}

/* Rolling sessions: while this tab is open the workspace quietly renews
   the sign-in every hour, so a long shift never ends mid-visit. */
let refreshTimer = null;

function startSessionRefresh() {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(async () => {
    if (!state.token) return;
    try {
      const data = await api("/auth/refresh", { method: "POST" });
      state.token = data.token;
      const raw = localStorage.getItem("medflow.session");
      if (raw) {
        const session = JSON.parse(raw);
        session.token = data.token;
        localStorage.setItem("medflow.session", JSON.stringify(session));
      }
    } catch { /* next hour will retry; 401s already force logout */ }
  }, 60 * 60 * 1000);
}

function enterApp() {
  startSessionRefresh();
  $("#login-gate").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#whoami").textContent =
    `${state.user.display_name} · ${state.user.role}` +
    (state.user.temporary ? " (temporary)" : "");
  const perms = new Set(state.user.permissions || []);
  const temporary = !!state.user.temporary;
  $("#btn-new-patient").classList.toggle("hidden", !perms.has("patients.create"));
  loadDepartments();
  loadTemplateFields();
  $("#btn-delete-patient").classList.toggle("hidden", !perms.has("patients.delete"));
  $("#btn-new-appt").classList.toggle("hidden", !perms.has("appointments.manage"));
  $("#nav-access").classList.toggle("hidden", !perms.has("users.manage"));
  $("#nav-settings").classList.toggle("hidden", !perms.has("settings.manage") && !perms.has("export.data"));
  $("#btn-pair-desktop").classList.toggle("hidden", temporary);
  $("#perm-note").textContent = temporary
    ? `temporary access${state.user.expires_at ? " until " + state.user.expires_at.replace("T", " ") : ""}`
    : perms.size ? `${perms.size} permissions` : "read-only session";
  showView("dashboard");
  loadDashboard();
  initBell();
  initSettingsNav();
  initTempAccessForm();
  // Facility metadata is no longer public on /api/health. Only ask for
  // operational metrics when this user has the existing reports permission.
  if (perms.has("reports.view")) {
    api("/system/metrics").then(metrics =>
      $("#facility-label").textContent = `— ${metrics.facility}`).catch(() => {});
  }
}

/* ------------------------------------------------------------------ nav */

function showView(name) {
  $$(".view").forEach(v => v.classList.add("hidden"));
  $(`#view-${name}`).classList.remove("hidden");
  $$(".nav-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.view === name));
}

$$(".nav-btn").forEach(btn =>
  btn.addEventListener("click", () => {
    showView(btn.dataset.view);
    if (btn.dataset.view === "dashboard") loadDashboard();
    if (btn.dataset.view === "patients") loadPatients();
    if (btn.dataset.view === "directory") loadDirectory();
    if (btn.dataset.view === "appointments") loadAppointments();
    if (btn.dataset.view === "reports") loadReports();
    if (btn.dataset.view === "analytics") loadAnalytics();
    if (btn.dataset.view === "settings") loadSettings();
    if (btn.dataset.view === "access") loadTempUsers();
    if (btn.dataset.view === "activity") loadActivity();
  }));

/* sidebar collapse on narrow screens — the toggle lives OUTSIDE the nav so
   it survives hiding the menu (restores the "no way back in" bug) */
const sideBar = document.getElementById("side");
const toggleBtn = document.getElementById("side-collapse");
if (sideBar && toggleBtn) {
  document.body.appendChild(toggleBtn);   // move button out of the nav
  toggleBtn.addEventListener("click", () => {
    const collapsed = sideBar.style.display === "none";
    sideBar.style.display = collapsed ? "" : "none";
    toggleBtn.textContent = collapsed ? "◀ Hide menu" : "▶ Show menu";
    toggleBtn.classList.toggle("floating", !collapsed);
    toggleBtn.style.position = "";
    toggleBtn.style.top = "";
    toggleBtn.style.left = "";
    toggleBtn.style.zIndex = "";
    toggleBtn.style.background = "";
    toggleBtn.style.border = "";
    toggleBtn.style.padding = "";
    toggleBtn.style.borderRadius = "";
  });
}

/* ------------------------------------------------------------------ dashboard */

async function loadDashboard() {
  try {
    const stats = await api("/reports/dashboard");
    $("#st-total").textContent = stats.total_patients;
    $("#st-week").textContent = stats.new_patients_7d;
    $("#st-appts").textContent = stats.appointments_today;
    $("#st-dx").textContent = stats.active_diagnoses;
    $("#st-crit").textContent = stats.critical_labs;
    const perms = new Set(state.user.permissions || []);
    const dashNew = $("#btn-dash-new-patient");
    if (dashNew)
      dashNew.style.display = perms.has("patients.create") ? "" : "none";
    $("#st-crit").closest(".stat").style.borderColor =
      stats.critical_labs > 0 ? "var(--danger)" : "";

    const [appts, audit] = await Promise.all([
      api("/appointments?scope=upcoming"),
      api("/reports/audit"),
    ]);
    fillTable($("#dash-appts"), appts.slice(0, 6), [
      ["patient_name", "Patient"],
      ["scheduled_at", "When"],
      ["provider", "Provider"],
    ], { datetime: ["scheduled_at"] });

    fillTable($("#dash-activity"), (audit.rows || []).slice(0, 6), [
      [null, "When", r => r[0]],
      [null, "Actor", r => r[1]],
      [null, "Action", r => r[2]],
    ]);
  } catch (err) {
    toast(err.message);
  }
}

/* ------------------------------------------------------------------ departments */

let deptCache = [];

async function loadDepartments() {
  try {
    deptCache = await api("/departments");
    renderPfDepartments();
    const inviteUnit = $("#invite-unit");
    if (inviteUnit) {
      const cur = inviteUnit.value;
      inviteUnit.innerHTML = '<option value="">No department</option>' +
        deptCache.filter(d => d.kind !== "organization")
          .map(d => `<option value="${esc(d.id)}">${esc(d.name)}</option>`).join("");
      if ([...inviteUnit.options].some(o => o.value === cur)) inviteUnit.value = cur;
    }
    const table = $("#departments-table");
    if (table) {
      const perms = new Set(state.user.permissions || []);
      fillTable(table, deptCache, [
        ["name", "Department"],
        ["patient_count", "Patients"],
        [null, "", () => ""],
      ]);
      if (perms.has("settings.manage")) {
        $$("#departments-table tbody tr").forEach((tr, i) => {
          const cell = tr.lastElementChild;
          const dept = deptCache[i];
          if (!dept || tr.querySelector("td[colspan]")) return;
          cell.innerHTML = "";
          const rename = document.createElement("button");
          rename.className = "btn ghost small";
          rename.textContent = "Rename";
          rename.addEventListener("click", async () => {
            const name = prompt("Rename department", dept.name);
            if (!name || name === dept.name) return;
            try {
              await api(`/org/units/${dept.id}`, {
                method: "PATCH", body: JSON.stringify({ name }),
              });
              toast("Department renamed", "ok");
              loadDepartments();
            } catch (err) { toast(err.message); }
          });
          const del = document.createElement("button");
          del.className = "btn danger small";
          del.textContent = "Delete";
          if (dept.kind === "organization" || dept.patient_count > 0) del.disabled = true;
          del.title = dept.patient_count > 0
            ? "Move this department's patients first"
            : "Delete department";
          del.addEventListener("click", async () => {
            if (!confirm(`Delete department "${dept.name}"?`)) return;
            try {
              await api(`/org/units/${dept.id}`, { method: "DELETE" });
              toast("Department deleted", "ok");
              loadDepartments();
            } catch (err) { toast(err.message); }
          });
          cell.append(rename, del);
        });
      }
    }
  } catch (err) {
    toast(err.message);
  }
}

$("#btn-dept-new")?.addEventListener("click", async () => {
  const name = prompt("Name the new department (e.g. Maternity, Outpatient, Pharmacy):", "");
  if (!name || !name.trim()) return;
  try {
    await api("/org/units", {
      method: "POST",
      body: JSON.stringify({ name: name.trim(), kind: "department" }),
    });
    toast(`Department "${name.trim()}" created`, "ok");
    loadDepartments();
  } catch (err) { toast(err.message); }
});

/* ------------------------------------------------------- record template */

let templateCache = [];

async function loadTemplateFields() {
  try {
    templateCache = await api("/template/fields?all=true");
    const table = $("#template-table");
    if (table) {
      const perms = new Set(state.user.permissions || []);
      fillTable(table, templateCache, [
        ["label", "Field"],
        ["section", "Section"],
        ["value_type", "Answers"],
        [null, "", () => ""],
      ]);
      if (perms.has("settings.manage")) {
        $$("#template-table tbody tr").forEach((tr, i) => {
          const cell = tr.lastElementChild;
          const field = templateCache[i];
          if (!field || tr.querySelector("td[colspan]")) return;
          cell.innerHTML = "";
          const rename = document.createElement("button");
          rename.className = "btn ghost small";
          rename.textContent = "Edit";
          rename.addEventListener("click", () => editTemplateField(field));
          const del = document.createElement("button");
          del.className = "btn danger small";
          del.textContent = "Remove";
          if (!field.active) del.disabled = true;
          del.title = "Takes the field off the chart; saved values are kept";
          del.addEventListener("click", async () => {
            if (!confirm(`Remove "${field.label}" from the chart? Nothing already saved is deleted.`)) return;
            try {
              await api(`/template/fields/${field.template_id}`, { method: "DELETE" });
              toast(`"${field.label}" removed from the chart`, "ok");
              loadTemplateFields();
            } catch (err) { toast(err.message); }
          });
          cell.append(rename, del);
        });
      }
      templateCache.forEach((f, i) => {
        const tr = table.querySelectorAll("tbody tr")[i];
        if (tr && !f.active) tr.style.opacity = "0.55";
      });
    }
  } catch (err) { toast(err.message); }
}

function editTemplateField(field) {
  const label = prompt("Field name:", field.label);
  if (label === null) return;
  const section = prompt("Section (grouping on the chart):", field.section || "General");
  if (section === null) return;
  let choices = field.choices || "";
  if (field.value_type === "choice") {
    const next = prompt("List options, comma-separated:", choices);
    if (next === null) return;
    choices = next;
  }
  const body = { label: label.trim(), section: section.trim() || "General" };
  if (field.value_type === "choice") body.choices = choices.trim();
  api(`/template/fields/${field.template_id}`, {
    method: "PATCH", body: JSON.stringify(body),
  }).then(() => { toast("Field updated", "ok"); loadTemplateFields(); })
    .catch(err => toast(err.message));
}

$("#template-form")?.addEventListener("submit", async e => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try {
    await api("/template/fields", { method: "POST", body: JSON.stringify(data) });
    toast(`Field "${data.label}" added`, "ok");
    e.target.reset();
    loadTemplateFields();
  } catch (err) { toast(err.message); }
});

function renderChartTemplate(sections) {
  const host = $("#chart-template");
  if (!host) return;
  const perms = new Set(state.user.permissions || []);
  const canEdit = perms.has("records.edit");
  host.innerHTML = "";
  const names = Object.keys(sections || {});
  if (!names.length) {
    host.innerHTML = '<p class="muted small">No custom fields yet — add some in Settings → Record template.</p>';
    return;
  }
  for (const section of names) {
    const head = document.createElement("p");
    head.className = "muted small";
    head.style.margin = "8px 0 2px";
    head.textContent = section;
    host.appendChild(head);
    for (const f of sections[section]) {
      const row = document.createElement("div");
      row.className = "tpl-row";
      let input;
      if (!canEdit) {
        input = document.createElement("span");
        input.textContent = f.value || "—";
      } else if (f.value_type === "choice" && f.choices) {
        input = document.createElement("select");
        input.dataset.templateId = f.template_id;
        input.innerHTML = '<option value="">—</option>' +
          f.choices.split(",").map(c => c.trim()).filter(Boolean)
            .map(c => `<option value="${esc(c)}" ${f.value === c ? "selected" : ""}>${esc(c)}</option>`).join("");
      } else if (f.value_type === "date") {
        input = document.createElement("input");
        input.type = "date";
        input.value = (f.value || "").slice(0, 10);
        input.dataset.templateId = f.template_id;
      } else {
        input = document.createElement("input");
        input.type = f.value_type === "number" ? "number" : "text";
        input.step = "any";
        input.value = f.value || "";
        input.placeholder = f.value ? "" : "Not filled in yet";
        input.dataset.templateId = f.template_id;
      }
      const label = document.createElement("label");
      label.textContent = f.label + (f.unit ? ` (${f.unit})` : "");
      row.append(label, input);
      if (f.updated_by) {
        const who = document.createElement("span");
        who.className = "muted tiny";
        who.textContent = `${fmtDT(f.updated_at)} · ${f.updated_by}`;
        row.appendChild(who);
      }
      host.appendChild(row);
    }
  }
}

$("#btn-template-save")?.addEventListener("click", async () => {
  const pid = state.currentPatient?.patient_id;
  if (!pid) return toast("No patient open");
  const values = {};
  let touched = 0;
  $$("#chart-template [data-template-id]").forEach(inp => {
    touched++;
    values[inp.dataset.templateId] = inp.value;
  });
  if (!touched) return toast("Nothing to save");
  try {
    await api(`/patients/${pid}/template`, {
      method: "PUT", body: JSON.stringify({ values }),
    });
    toast("Custom fields saved — history updated", "ok");
    openChart(pid);
  } catch (err) { toast(err.message); }
});

/* ------------------------------------------------------------------ patients */

let searchTimer = null;
$("#patient-search").addEventListener("input", e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadPatients(e.target.value), 200);
});

async function loadPatients(query = "") {
  try {
    state.patients = await api(`/patients?q=${encodeURIComponent(query)}`);
    const deptName = new Map(deptCache.map(d => [d.id, d.name]));
    fillTable($("#patients-table"), state.patients, [
      ["patient_number", "No"],
      ["name", "Name"],
      ["age", "Age"],
      ["sex", "Sex"],
      [null, "Department", r => deptName.get(r.origin_unit_id) || "—"],
      ["diagnosis", "Diagnosis"],
      ["updated_at", "Updated"],
    ], {
      datetime: ["updated_at"],
      onRowClick: s => openChart(s.patient_id),
    });
  } catch (err) {
    toast(err.message);
  }
}

/* ---------------------------------------------------------- bulk import */

$("#btn-import").addEventListener("click", () => {
  $("#import-panel").classList.toggle("hidden");
});
$("#btn-import-cancel").addEventListener("click", () => {
  $("#import-panel").classList.add("hidden");
  $("#import-report").classList.add("hidden");
});

$("#btn-import-run").addEventListener("click", async () => {
  const text = $("#import-text").value.trim();
  if (!text) return toast("Paste some rows first");
  const lines = text.split(/\r?\n/).filter(l => l.trim());
  const headers = lines[0].split(/[,;\t]/).map(h => h.trim().toLowerCase());
  const rows = lines.slice(1).map(line => {
    const cells = line.split(/[,;\t]/).map(c => c.trim());
    const row = {};
    headers.forEach((h, i) => { if (h) row[h] = cells[i] ?? ""; });
    return row;
  }).filter(r => Object.values(r).some(v => v));
  if (!rows.length) return toast("No data rows found under the header");
  try {
    const report = await api("/patients/import", {
      method: "POST", body: JSON.stringify({ rows }),
    });
    const rep = $("#import-report");
    rep.classList.remove("hidden");
    rep.innerHTML =
      `<p class="ok">Imported ${esc(report.created)} of ${esc(report.total)} record(s).</p>` +
      (report.failed.length
        ? `<p class="warn-text">${esc(report.failed.length)} row(s) need attention:</p><ul class="plain-list">` +
          report.failed.map(f =>
            `<li>Row ${esc(f.row)}${f.name ? ` (${esc(f.name)})` : ""}: ${esc(f.error)}</li>`).join("") +
          "</ul>"
        : "");
    loadPatients();
  } catch (err) { toast(err.message); }
});

/* --------------------------------------------------------------- directory */

async function loadDirectory() {
  const perms = new Set(state.user.permissions || []);
  if (!perms.has("patients.view")) return;
  try {
    /* department roster */
    const sel = $("#dir-dept");
    const current = sel.value;
    sel.innerHTML = '<option value="">Whole facility</option>' +
      deptCache.map(d => d.kind === "organization"
        ? "" : `<option value="${esc(d.id)}">${esc(d.name)}</option>`).join("");
    if ([...sel.options].some(o => o.value === current)) sel.value = current;
    const roster = await api(
      `/patients/by-department${sel.value ? `?department_id=${sel.value}` : ""}`);
    fillTable($("#dir-dept-table"), roster, [
      ["patient_number", "No"],
      ["name", "Name"],
      ["diagnosis", "Diagnosis"],
    ], { onRowClick: s => openChart(s.patient_id) });

    /* condition directory */
    const dxs = await api("/diagnoses");
    fillTable($("#dir-dx-table"), dxs, [
      ["description", "Condition"],
      ["patients", "Patients"],
      [null, "", () => ""],
    ]);
    $$("#dir-dx-table tbody tr").forEach((tr, i) => {
      if (!dxs[i] || tr.querySelector("td[colspan]")) return;
      tr.style.cursor = "pointer";
      tr.addEventListener("click", () => showDxPatients(dxs[i].description));
    });
  } catch (err) {
    toast(err.message);
  }
}

async function showDxPatients(description) {
  $("#dir-dx-title").textContent = `Patients with “${description}”`;
  try {
    const rows = await api(`/patients/by-diagnosis?q=${encodeURIComponent(description)}`);
    fillTable($("#dir-dx-patients"), rows, [
      ["patient_number", "No"],
      ["name", "Name"],
      ["age", "Age"],
      ["diagnosis", "Diagnosis"],
      ["updated_at", "Updated"],
    ], { datetime: ["updated_at"], onRowClick: s => openChart(s.patient_id) });
    $("#dir-dx-card").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    toast(err.message);
  }
}

$("#dir-dept").addEventListener("change", loadDirectory);
$("#dir-dx-search").addEventListener("input", debounce(async () => {
  try {
    const q = $("#dir-dx-search").value;
    const dxs = await api(`/diagnoses?q=${encodeURIComponent(q)}`);
    fillTable($("#dir-dx-table"), dxs, [
      ["description", "Condition"],
      ["patients", "Patients"],
      [null, "", () => ""],
    ]);
    $$("#dir-dx-table tbody tr").forEach((tr, i) => {
      if (!dxs[i] || tr.querySelector("td[colspan]")) return;
      tr.style.cursor = "pointer";
      tr.addEventListener("click", () => showDxPatients(dxs[i].description));
    });
  } catch (err) { toast(err.message); }
}, 250));

/* ------------------------------------------------------------------ chart */

async function openChart(patientId) {
  try {
    const chart = await api(`/patients/${patientId}/chart`);
    state.currentPatient = chart.patient;
    showView("chart");
    $("#chart-head").innerHTML = `
      <div class="chart-title">
        <h2>${esc(chart.patient.name)}</h2>
        <span class="pnum">${esc(chart.patient.patient_number)}</span>
        <span class="tag">${esc(chart.patient.sex || "sex n/a")}</span>
        ${chart.patient.age != null ? `<span class="tag">${esc(chart.patient.age)}y</span>` : ""}
        ${chart.patient.origin_unit_id && deptName(chart.patient.origin_unit_id) ? `<span class="tag">${esc(deptName(chart.patient.origin_unit_id))}</span>` : ""}
        ${chart.patient.blood_pressure ? `<span class="tag warn">BP ${esc(chart.patient.blood_pressure)}</span>` : ""}
      </div>
      <p class="muted small">${esc(chart.patient.medical_history || "No medical history recorded")}</p>`;

    renderList("#chart-allergies", chart.allergies,
      a => `${esc(a.substance)} <span class="tag ${a.severity === "severe" ? "crit" : ""}">${esc(a.severity)}</span> ${esc(a.reaction || "")}`);
    renderList("#chart-diagnoses", chart.diagnoses,
      d => `${esc(d.description)} <span class="tag">${esc(d.status)}</span> ${esc(d.code || "")}`);
    renderList("#chart-medications", chart.medications,
      m => `${esc(m.name)} ${esc(m.dose || "")} ${esc(m.frequency || "")} <span class="tag">${esc(m.status)}</span>`);
    renderList("#chart-vitals", chart.vitals,
      v => `${fmtDT(v.recorded_at)} — BP ${esc(v.blood_pressure || "—")} · HR ${esc(v.heart_rate ?? "—")} · ${esc(v.temperature_c ?? "—")}°C · SpO₂ ${esc(v.oxygen_saturation ?? "—")}%`);
    renderList("#chart-lab_results", chart.lab_results,
      l => `${esc(l.panel)} · ${esc(l.analyte)}: <strong>${esc(l.value || "—")}</strong> ${esc(l.unit || "")} <span class="tag ${l.flag === "critical" ? "crit" : l.flag === "abnormal" ? "warn" : ""}">${esc(l.flag)}</span>`);
    renderList("#chart-notes", chart.notes,
      n => `${fmtDT(n.created_at)} <em>(${esc(n.category)})</em> — ${esc(n.body)}`);
    renderList("#chart-timeline", chart.timeline,
      t => `${fmtDT(t.created_at)} — ${esc(t.description)}`);

    /* facility-defined fields, grouped by section */
    try {
      const tpl = await api(`/patients/${patientId}/template`);
      renderChartTemplate(tpl);
    } catch { renderChartTemplate({}); }

    /* departments this patient belongs to */
    try {
      const pdepts = await api(`/patients/${patientId}/departments`);
      const host = $("#chart-departments");
      if (host) host.innerHTML = pdepts.length
        ? pdepts.map(d => `<span class="picked-chip">${esc(d.name)}</span>`).join(" ")
        : '<span class="muted tiny">No department</span>';
    } catch { /* optional */ }

    /* record history: who changed what, when */
    try {
      const versions = await api(`/patients/${patientId}/versions`);
      fillTable($("#chart-versions"), versions.slice(0, 40), [
        ["created_at", "When", r => fmtDT(r.created_at)],
        ["description", "Change"],
        ["actor", "By", r => esc(r.actor || "system")],
      ]);
    } catch { fillTable($("#chart-versions"), [], [["", ""]]); }

    $("#chart-print").href = `/api/patients/${patientId}/chart.html`;
  } catch (err) {
    toast(err.message);
  }
}

/* add chart entries via the inline forms */
$$("form[data-add]").forEach(form => {
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const section = form.dataset.add;
    const data = Object.fromEntries(new FormData(form));
    const pid = state.currentPatient?.patient_id;
    if (!pid) return toast("No patient open");
    const pathMap = {
      allergies: "allergies", diagnoses: "diagnoses", medications: "medications",
      vitals: "vitals", lab_results: "lab-results", notes: "notes",
    };
    try {
      await api(`/patients/${pid}/${pathMap[section]}`, {
        method: "POST", body: JSON.stringify(data),
      });
      form.reset();
      openChart(pid);
    } catch (err) {
      toast(err.message);
    }
  });
});

$("#btn-back").addEventListener("click", () => {
  showView("patients");
  loadPatients();
});

$("#btn-delete-patient").addEventListener("click", async () => {
  const p = state.currentPatient;
  if (!p || !confirm(`Delete record for ${p.name}? It can be restored from backups.`)) return;
  try {
    await api(`/patients/${p.patient_id}`, { method: "DELETE" });
    toast("Record deleted");
    showView("patients");
    loadPatients();
  } catch (err) {
    toast(err.message);
  }
});

/* ------------------------------------------------------------------ appointments */

async function loadAppointments() {
  try {
    /* provider filter menu */
    const sel = $("#appt-provider");
    if (sel) {
      const current = sel.value;
      const providers = await api("/appointments/providers");
      sel.innerHTML = '<option value="">All providers</option>' +
        providers.map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
      if (providers.includes(current)) sel.value = current;
    }
    const prov = sel && sel.value ? `&provider=${encodeURIComponent(sel.value)}` : "";
    const appts = await api(`/appointments?scope=upcoming${prov}`);
    fillTable($("#appts-table"), appts, [
      ["patient_name", "Patient"],
      ["scheduled_at", "When"],
      ["provider", "Provider"],
      ["reason", "Reason"],
      ["status", "Status"],
    ], { datetime: ["scheduled_at"] });

    /* “your next patients” — the signed-in clinician's upcoming book */
    const mine = $("#appt-mine");
    if (mine) {
      const me = state.user.display_name;
      const myAppts = await api(`/appointments?scope=upcoming&provider=${encodeURIComponent(me)}`);
      if (myAppts.length) {
        const next = myAppts[0];
        mine.innerHTML = `<strong>${esc(myAppts.length)}</strong> upcoming appointment(s) booked for you — ` +
          `next: ${esc(next.patient_name)} at ${fmtDT(next.scheduled_at)}.`;
        mine.classList.remove("hidden");
      } else {
        mine.classList.add("hidden");
      }
    }
  } catch (err) {
    toast(err.message);
  }
}

$("#appt-provider")?.addEventListener("change", loadAppointments);

/* ------------------------------------------------------------------ analytics */

async function loadAnalytics() {
  try {
    const a = await api("/analytics");
    $("#an-patients").textContent = a.patients_total ?? "–";
    $("#an-today").textContent = a.appointments_today ?? "–";
    $("#an-dx").textContent = a.active_diagnoses ?? "–";
    $("#an-crit").textContent = a.critical_labs ?? "–";

    fillTable($("#an-weeks"), a.registrations_by_week || [], [
      ["day", "Day"],
      ["count", "New patients"],
    ]);
    const f = a.appointment_funnel || {};
    fillTable($("#an-funnel"), Object.entries(f).map(([k, v]) =>
      ({ stage: k.replace(/_/g, " "), count: v })), [
      ["stage", "Stage"],
      ["count", "Appointments"],
    ]);
    fillTable($("#an-dx-list"), a.top_diagnoses || [], [
      ["diagnosis", "Condition"],
      ["count", "Patients"],
    ]);
    fillTable($("#an-work"), a.provider_workload || [], [
      ["provider", "Provider"],
      ["appointments", "Appointments"],
      ["completed", "Completed"],
    ]);
    const cb = a.cloud_backup;
    $("#an-storage").textContent = !cb
      ? "Database lives on this computer; off-site copies are not switched on yet."
      : `Off-site copies ${cb.enabled ? "are enabled" : "are configured but off"} ` +
        `(${cb.provider}). Last upload ${cb.last_upload_status || "—"} at ${cb.last_upload_at || "—"}.`;
  } catch (err) {
    toast(err.message);
  }
}

/* ------------------------------------------------------------------ activity */

async function loadActivity() {
  try {
    const audit = await api("/reports/audit");
    fillTable($("#activity-table"), audit.rows || [], [
      [null, "When", r => r[0]],
      [null, "Actor", r => r[1]],
      [null, "Action", r => r[2]],
      [null, "Entity", r => `${r[3]} ${r[4] || ""}`],
      [null, "Details", r => r[5]],
    ]);
  } catch (err) {
    toast(err.message);
  }
}

/* ------------------------------------------------------------------ reports */

async function loadReports() {
  try {
    const [dx, prov] = await Promise.all([
      api("/reports/diagnoses"), api("/reports/appointments"),
    ]);
    fillTable($("#reports-dx"), (dx.rows || dx.top_diagnoses || []).slice(0, 8), [
      [null, "Diagnosis", r => r.diagnosis || r[0] || "Unspecified"],
      [null, "Patients", r => r.count ?? r[1] ?? "—"],
    ]);
    fillTable($("#reports-prov"), (prov.rows || prov.workload || []).slice(0, 8), [
      [null, "Provider", r => r.provider || r[0] || "—"],
      [null, "Appointments", r => r.appointments ?? r[1] ?? "—"],
      [null, "Completed", r => r.completed ?? r[2] ?? "—"],
    ]);
  } catch (err) {
    toast(err.message);
  }
}

/* authorized downloads: fetch with the Bearer token, then save the blob */
$$("#export-row [data-export]").forEach(btn =>
  btn.addEventListener("click", async () => {
    const name = btn.dataset.export, fmt = btn.dataset.fmt;
    try {
      const res = await fetch(`/api/export/${name}.${fmt}`, {
        headers: { Authorization: `Bearer ${state.token}` },
      });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `medflow_${name}.${fmt}`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (err) {
      toast(err.message);
    }
  }));

/* ------------------------------------------------------------------ settings */

async function loadSettings() {
  // Facility counts are operational metrics and require the existing permission.
  if (new Set(state.user.permissions || []).has("reports.view")) {
    api("/system/metrics").then(metrics =>
      $("#settings-facility").textContent =
        `${metrics.facility} — ${metrics.patients} patient record(s)`).catch(() => {});
  }
  initSettingsNav();
  loadBackups();
  loadBin();
  loadCloudBackup();
  loadSessionPolicy();
  const perms = new Set(state.user.permissions || []);
  if (perms.has("users.manage")) loadStaff();
  if (perms.has("settings.manage")) loadRules();
}

async function loadBackups() {
  try {
    const backups = await api("/backups");
    fillTable($("#backups-table"), backups.slice(0, 6), [
      ["name", "Snapshot"],
      ["size_display", "Size"],
    ]);
  } catch (err) {
    fillTable($("#backups-table"), [], [["", ""]]);
  }
}

$("#btn-backup-now").addEventListener("click", async () => {
  try {
    const r = await api("/backups", { method: "POST" });
    toast(`Backup saved: ${r.created}`, "ok");
    loadBackups();
  } catch (err) { toast(err.message); }
});

$("#btn-backup-prune").addEventListener("click", async () => {
  try {
    const r = await api("/backups/prune", { method: "POST" });
    toast(`Removed ${r.removed} old backup(s)`, "ok");
    loadBackups();
  } catch (err) { toast(err.message); }
});

/* --------------------------------------------------- session policy UI */

async function loadSessionPolicy() {
  const form = $("#session-form");
  if (!form) return;
  try {
    const s = await api("/settings/session");
    $("#sess-remember").checked = s.remember_me_days > 0;
    $("#sess-days").value = String(Math.min(7, Math.max(1, s.remember_me_days || 7)));
    $("#sess-logout").checked = s.logouts_enabled !== false;
    const btn = $("#btn-logout");
    if (btn) btn.classList.toggle("hidden", s.logouts_enabled === false);
    const kind = s.sliding_refresh ? "renews while in use" : "fixed length";
    $("#session-status").textContent =
      `Now: ${s.token_ttl_hours}-hour sign-ins` +
      (s.remember_me_days
        ? `, “stay signed in” keeps people in for up to ${s.remember_me_days} day(s), sessions ${kind}.`
        : `, sessions ${kind}.`);
    const perms = new Set(state.user.permissions || []);
    [...form.querySelectorAll("input,select,button")].forEach(
      el => (el.disabled = !perms.has("users.manage")));
  } catch { /* non-admins see the summary only */ }
}

$("#btn-session-save").addEventListener("click", async () => {
  try {
    const days = $("#sess-remember").checked ? parseInt($("#sess-days").value, 10) : 1;
    const r = await api("/settings/session", {
      method: "PATCH",
      body: JSON.stringify({
        token_ttl_hours: 12,
        remember_me_days: days,
        logouts_enabled: $("#sess-logout").checked,
        sliding_refresh: true,
      }),
    });
    toast("Session settings saved", "ok");
    loadSessionPolicy();
    const btn = $("#btn-logout");
    if (btn) btn.classList.toggle("hidden", r.logouts_enabled === false);
  } catch (err) { toast(err.message); }
});

/* ------------------------------------------------------ off-site cloud */

function cloudMsg(text, isErr = false) {
  const el = $("#cloud-msg");
  el.textContent = text;
  el.style.color = isErr ? "var(--danger)" : "";
  el.classList.remove("hidden");
}

async function loadCloudBackup() {
  try {
    const c = await api("/settings/cloud-backup");
    $("#cloud-card").classList.toggle("hidden", false);
    const state_text = c.enabled
      ? (c.configured ? `On — ${c.provider}` : "On — settings incomplete")
      : "Off";
    const last = c.last_upload_status === "ok" && c.last_upload_at
      ? ` · last upload: ${c.last_upload_at}`
      : (c.last_upload_status ? ` · last: ${c.last_upload_status}` : "");
    $("#cloud-status").textContent = `${state_text}${last}`;
    const perms = new Set(state.user.permissions || []);
    if (perms.has("settings.manage")) {
      $("#cloud-form").classList.remove("hidden");
      if (c.configured) $("#cloud-upload-form").classList.remove("hidden");
      $("#cloud-provider").value = c.provider === "webdav" ? "webdav" : "s3";
      $("#cloud-endpoint").value = c.endpoint || "";
      $("#cloud-bucket").value = c.bucket || "";
      $("#cloud-prefix").value = c.prefix || "";
      $("#cloud-enabled").checked = !!c.enabled;
    }
  } catch {
    $("#cloud-card").classList.add("hidden");   // no settings.manage → hide
  }
}

$("#cloud-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    provider: $("#cloud-provider").value,
    endpoint: $("#cloud-endpoint").value.trim(),
    bucket: $("#cloud-bucket").value.trim(),
    prefix: $("#cloud-prefix").value.trim(),
    enabled: $("#cloud-enabled").checked,
  };
  if ($("#cloud-access").value.trim()) body.access_key_id = body.username = $("#cloud-access").value.trim();
  if ($("#cloud-secret").value) body.secret_access_key = body.password = $("#cloud-secret").value;
  try {
    await api("/settings/cloud-backup", { method: "PUT", body: JSON.stringify(body) });
    $("#cloud-access").value = ""; $("#cloud-secret").value = "";
    cloudMsg("Saved. Use “Test connection” to verify, then “Back up to cloud now”.", false);
    loadCloudBackup();
  } catch (err) { cloudMsg(err.message, true); }
});

$("#btn-cloud-test")?.addEventListener("click", async () => {
  try {
    const r = await api("/settings/cloud-backup/test", { method: "POST" });
    cloudMsg(r.ok ? `Connection OK — ${r.objects} backup(s) already stored.`
                  : `Not working: ${r.error}`, !r.ok);
  } catch (err) { cloudMsg(err.message, true); }
});

$("#cloud-upload-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const pass = $("#cloud-passphrase").value;
  if (pass.length < 8) { cloudMsg("Passphrase needs at least 8 characters.", true); return; }
  try {
    const r = await api("/settings/cloud-backup/upload", {
      method: "POST", body: JSON.stringify({ passphrase: pass }),
    });
    $("#cloud-passphrase").value = "";
    cloudMsg(`Encrypted copy uploaded (${Math.round(r.bytes / 1024)} KB) — keep that passphrase safe.`, false);
    toast("Off-site backup uploaded", "ok");
    loadCloudBackup();
  } catch (err) { cloudMsg(err.message, true); }
});

async function loadBin() {
  try {
    const rows = await api("/patients/deleted");
    fillTable($("#bin-table"), rows, [
      ["patient_number", "No"],
      ["name", "Name"],
      [null, "", () => ""],
    ]);
    $$("#bin-table tbody tr").forEach((tr, i) => {
      const cell = tr.lastElementChild;
      if (rows[i] && !tr.querySelector("td[colspan]")) {
        const btn = document.createElement("button");
        btn.className = "btn";
        btn.textContent = "Restore";
        btn.style.padding = "4px 10px";
        btn.addEventListener("click", async () => {
          try {
            await api(`/patients/${rows[i].patient_id}/restore`, { method: "POST" });
            toast("Record restored", "ok");
            loadBin();
          } catch (err) { toast(err.message); }
        });
        cell.appendChild(btn);
      }
    });
  } catch (err) {
    fillTable($("#bin-table"), [], [["", ""]]);
  }
}

async function loadStaff() {
  try {
    const users = await api("/org/users");
    const unitName = new Map(deptCache.map(d => [d.id, d.name]));
    fillTable($("#staff-table"), users, [
      ["username", "Username"],
      ["display_name", "Name"],
      [null, "Job title", r => esc(r.job_title || "—")],
      [null, "Department", r => unitName.get(r.unit_id) || "—"],
      [null, "Phone", r => esc(r.phone || "—")],
      ["role", "Role"],
      [null, "State", r => r.active ? "active" : "disabled"],
      [null, "", () => ""],
    ]);
    const unitSel = $("#staff-unit");
    if (unitSel) {
      const cur = unitSel.value;
      unitSel.innerHTML = '<option value="">No department</option>' +
        deptCache.filter(d => d.kind !== "organization")
          .map(d => `<option value="${esc(d.id)}">${esc(d.name)}</option>`).join("");
      if ([...unitSel.options].some(o => o.value === cur)) unitSel.value = cur;
    }
    $$("#staff-table tbody tr").forEach((tr, i) => {
      const u = users[i];
      if (u && !tr.querySelector("td[colspan]")) {
        const cell = tr.lastElementChild;
        const edit = document.createElement("button");
        edit.className = "btn ghost";
        edit.style.padding = "4px 10px";
        edit.textContent = "Edit";
        edit.addEventListener("click", () => {
          const title = prompt("Job title (blank to clear)", u.job_title || "");
          if (title === null) return;
          const phone = prompt("Phone (blank to clear)", u.phone || "");
          if (phone === null) return;
          api(`/org/users/${u.user_id}`, {
            method: "PATCH",
            body: JSON.stringify({ job_title: title, phone: phone }),
          }).then(loadStaff).catch(err => toast(err.message));
        });
        const toggle = document.createElement("button");
        toggle.className = "btn";
        toggle.style.padding = "4px 10px";
        toggle.style.marginLeft = "6px";
        toggle.textContent = u.active ? "Disable" : "Enable";
        toggle.addEventListener("click", async () => {
          try {
            await api(`/org/users/${u.user_id}`, {
              method: "PATCH", body: JSON.stringify({ active: !u.active }),
            });
            loadStaff();
          } catch (err) { toast(err.message); }
        });
        cell.appendChild(edit);
        cell.appendChild(toggle);
      }
    });
  } catch (err) {
    fillTable($("#staff-table"), [], [["", ""]]);
  }
}

$("#staff-form")?.addEventListener("submit", async e => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  const roleMap = {
    physician: "physician", nurse: "nurse", reception: "reception",
    technician: "technician", viewer: "viewer", administrator: "administrator",
  };
  const payload = {
    username: data.username.trim().toLowerCase().replace(/\s+/g, "_"),
    display_name: data.display_name.trim(),
    password: data.password,
    role: roleMap[data.role] || data.role,
    job_title: data.job_title || undefined,
    phone: data.phone || undefined,
    unit_id: data.unit_id ? parseInt(data.unit_id, 10) : undefined,
  };
  try {
    await api("/org/users", { method: "POST", body: JSON.stringify(payload) });
    toast(`Account created for ${payload.display_name}`, "ok");
    e.target.reset();
    loadStaff();
  } catch (err) { toast(err.message); }
});

async function loadRules() {
  try {
    const rules = await api("/automation/rules");
    fillTable($("#rules-table"), rules, [
      ["name", "Rule"],
      ["fact", "Watch"],
      [null, "Condition", r => `${r.operator} ${r.threshold}`],
      ["action", "Action"],
      [null, "Last run", r => r.last_run_result || "never"],
      [null, "", () => ""],
    ]);
    $$("#rules-table tbody tr").forEach((tr, i) => {
      const rule = rules[i];
      if (rule && !tr.querySelector("td[colspan]")) {
        const cell = tr.lastElementChild;
        const btn = document.createElement("button");
        btn.className = "btn danger";
        btn.textContent = "Delete";
        btn.style.padding = "4px 10px";
        btn.addEventListener("click", async () => {
          try {
            await api(`/automation/rules/${rule.rule_id}`, { method: "DELETE" });
            loadRules();
          } catch (err) { toast(err.message); }
        });
        cell.appendChild(btn);
      }
    });
  } catch (err) {
    fillTable($("#rules-table"), [], [["", ""]]);
  }
}

$("#rule-form").addEventListener("submit", async e => {
  e.preventDefault();
  const raw = Object.fromEntries(new FormData(e.target));
  try {
    await api("/automation/rules", {
      method: "POST",
      body: JSON.stringify({ name: raw.name, fact: raw.fact,
        operator: raw.operator, threshold: parseFloat(raw.threshold),
        action: raw.action }),
    });
    e.target.reset();
    toast("Rule added", "ok");
    loadRules();
  } catch (err) { toast(err.message); }
});

$("#btn-rules-run").addEventListener("click", async () => {
  try {
    const report = await api("/automation/run", { method: "POST" });
    const fired = report.filter(r => r.fired).length;
    toast(`${fired} of ${report.length} rule(s) fired`, "ok");
    loadRules();
  } catch (err) { toast(err.message); }
});

/* ------------------------------------------------------------------ desktop pairing */

$("#btn-pair-desktop").addEventListener("click", async () => {
  try {
    const r = await api("/pairing/code", {
      method: "POST", body: JSON.stringify({ label: "Desktop workstation" }),
    });
    $("#pairing-code-display").textContent = r.code;
    $("#dlg-pairing").showModal();
  } catch (err) { toast(err.message); }
});

/* ------------------------------------------------------------------ dialogs */

const dlgPatient = $("#dlg-patient");

/* dashboard shortcut: register a patient without hunting for the section */
$("#btn-dash-new-patient")?.addEventListener("click", () => {
  $("#dlg-patient-title").textContent = "New patient";
  $("#form-patient").reset();
  pfDeptIds = [];
  renderPfDepartments();
  $("#form-patient-error").classList.add("hidden");
  dlgPatient.showModal();
});

/* --- age <-> date of birth: fill either one, the other follows --- */
const pfDob = $("#pf-dob"), pfAge = $("#pf-age");
pfDob?.addEventListener("change", () => {
  if (!pfDob.value) return;
  const dob = new Date(pfDob.value), now = new Date();
  let age = now.getFullYear() - dob.getFullYear();
  const m = now.getMonth() - dob.getMonth();
  if (m < 0 || (m === 0 && now.getDate() < dob.getDate())) age--;
  if (age >= 0 && age < 131) pfAge.value = age;
});
pfAge?.addEventListener("change", () => {
  const age = parseInt(pfAge.value, 10);
  if (!Number.isFinite(age) || age < 0 || age > 130) return;
  const d = new Date();
  d.setFullYear(d.getFullYear() - age);
  pfDob.value = d.toISOString().slice(0, 10);
  if (Number.isFinite(age)) pfDob.title =
    "Approximate — calculated from the age you typed (January 1).";
});

/* --- departments: tick every one that applies --- */
let pfDeptIds = [];
function renderPfDepartments() {
  const wrap = $("#pf-depts");
  if (!wrap) return;
  const list = deptCache.filter(d => d.kind !== "organization");
  wrap.innerHTML = list.length
    ? list.map(d => `<label><input type="checkbox" value="${esc(d.id)}" ${
        pfDeptIds.includes(d.id) ? "checked" : ""}> ${esc(d.name)}</label>`).join("")
    : '<span class="muted tiny">No departments yet — create some in Settings.</span>';
  wrap.querySelectorAll("input").forEach(cb => cb.addEventListener("change", () => {
    const id = parseInt(cb.value, 10);
    if (cb.checked) { if (!pfDeptIds.includes(id)) pfDeptIds.push(id); }
    else pfDeptIds = pfDeptIds.filter(x => x !== id);
  }));
}

/* --- friendly error line: '2 fields need attention: …' --- */
function showFormError(box, err) {
  const fields = err.fields || {};
  const parts = Object.entries(fields).map(([f, msgs]) =>
    `${labelFor(f)}: ${Array.isArray(msgs) ? msgs[0] : msgs}`);
  box.textContent = parts.length
    ? (parts.length === 1 ? parts[0]
       : `${parts.length} things need attention — ${parts.join(" · ")}`)
    : (err.message || "Something went wrong.");
  box.classList.remove("hidden");
}
const FIELD_LABELS = {
  name: "Full name", age: "Age", sex: "Sex", date_of_birth: "Date of birth",
  phone: "Phone", email: "Email", address: "Address",
  blood_pressure: "Blood pressure", heart_rate: "Heart rate",
  weight: "Weight", medical_history: "Medical history",
  diagnosis: "Diagnosis", notes: "Notes", department_id: "Department",
  scheduled_at: "Date & time", patient_id: "Patient", reason: "Reason",
  username: "Username", password: "Password", display_name: "Full name",
  unit_ids: "Departments", code: "Invite code",
};
function labelFor(field) { return FIELD_LABELS[field] || field.replace(/_/g, " "); }

$("#btn-patient-cancel").addEventListener("click", () => dlgPatient.close());

$("#btn-new-patient").addEventListener("click", () => {
  $("#dlg-patient-title").textContent = "New patient";
  $("#form-patient").reset();
  pfDeptIds = [];
  renderPfDepartments();
  $("#form-patient-error").classList.add("hidden");
  dlgPatient.showModal();
});

$("#form-patient").addEventListener("submit", async e => {
  if (e.submitter?.value !== "ok") return;
  e.preventDefault();
  const form = e.target;
  const data = Object.fromEntries(new FormData(form));
  const missing = ["name"].filter(k => !(data[k] || "").trim());
  if (missing.length) {
    showFormError($("#form-patient-error"), {
      fields: Object.fromEntries(missing.map(k => [k, ["is required"]])),
      message: "missing",
    });
    return;
  }
  try {
    const created = await api("/patients", {
      method: "POST", body: JSON.stringify(data),
    });
    if (pfDeptIds.length) {
      try {
        await api(`/patients/${created.patient_id}/departments`, {
          method: "PUT", body: JSON.stringify({ unit_ids: pfDeptIds }),
        });
      } catch (err) { toast(err.message); }
    }
    dlgPatient.close();
    toast(`Registered ${created.name} (${created.patient_number})`);
    showView("patients");
    loadPatients();
  } catch (err) {
    showFormError($("#form-patient-error"), err);
  }
});

const dlgAppt = $("#dlg-appointment");
$("#btn-appt-cancel").addEventListener("click", () => dlgAppt.close());
$("#btn-new-appt").addEventListener("click", async () => {
  $("#form-appointment").reset();
  $("#form-appointment-error").classList.add("hidden");
  try {
    const providers = await api("/appointments/providers");
    $("#provider-list").innerHTML =
      providers.map(p => `<option value="${esc(p)}">`).join("");
  } catch { /* fresh facilities have nobody on the books yet */ }
  dlgAppt.showModal();
});

$("#form-appointment").addEventListener("submit", async e => {
  if (e.submitter?.value !== "ok") return;
  e.preventDefault();
  const raw = Object.fromEntries(new FormData(e.target));
  const missing = [];
  if (!(raw.patient_id || "").trim()) missing.push("patient_id");
  if (!(raw.scheduled_at || "").trim()) missing.push("scheduled_at");
  if (missing.length) {
    showFormError($("#form-appointment-error"), {
      fields: Object.fromEntries(missing.map(k => [k, ["is required"]])),
      message: "missing",
    });
    return;
  }
  try {
    await api(`/appointments?patient_id=${raw.patient_id}`, {
      method: "POST",
      body: JSON.stringify({ ...raw, patient_id: undefined }),
    });
    dlgAppt.close();
    toast("Appointment booked — the staff member has been notified", "ok");
    loadAppointments();
  } catch (err) {
    showFormError($("#form-appointment-error"), err);
  }
});

$("#btn-logout").addEventListener("click", logout);

/* ------------------------------------------------------------------ temporary access */

async function loadTempUsers() {
  try {
    const guests = await api("/temp-users");
    fillTable($("#temp-table"), guests, [
      ["label", "Who"],
      ["username", "Username"],
      [null, "Expires", r => r.expires_at ? r.expires_at.replace("T", " ") : "—"],
      [null, "Patients", r => (r.patient_ids || []).join(", ") || "—"],
      [null, "Status", r => r.expired ? "expired" : (r.active ? "active" : "revoked")],
      [null, "", r => ""],
    ]);
    // turn the last cell of active rows into a revoke button
    const bodyRows = $$("#temp-table tbody tr")
      .filter(tr => !tr.querySelector("td[colspan]"));
    bodyRows.forEach((tr, i) => {
      const guest = guests[i];
      const cell = tr.lastElementChild;
      if (guest && guest.active && !guest.expired) {
        const btn = document.createElement("button");
        btn.className = "btn danger";
        btn.textContent = "Revoke";
        btn.style.padding = "4px 10px";
        btn.addEventListener("click", async () => {
          try {
            await api(`/temp-users/${guest.id}`, { method: "DELETE" });
            toast("Access revoked", "ok");
            loadTempUsers();
          } catch (err) {
            toast(err.message);
          }
        });
        cell.appendChild(btn);
      }
    });
  } catch (err) {
    toast(err.message);
  }
}

let tempPickedIds = [];

/* keep the guest form in plain English: patient picker instead of raw IDs */
function initTempAccessForm() {
  const form = $("#temp-form");
  if (!form) return;
  const pick = $("#temp-patient-pick");
  const dur = $("#temp-duration");
  const customWrap = $("#temp-custom-wrap");
  if (dur) dur.addEventListener("change", () => {
    customWrap?.classList.toggle("hidden", dur.value !== "custom");
  });
  if (pick) {
    api("/patients?limit=500").then(rows => {
      pick.innerHTML = '<option value="">— choose a patient —</option>' +
        rows.map(p => `<option value="${esc(p.patient_id)}">` +
          `${esc(p.name)} (${esc(p.patient_number || "#" + p.patient_id)})</option>`).join("");
    }).catch(() => {});
    pick.addEventListener("change", () => {
      const id = parseInt(pick.value, 10);
      const label = pick.options[pick.selectedIndex]?.textContent || "";
      if (Number.isInteger(id) && id > 0 && !tempPickedIds.some(x => x.id === id)) {
        tempPickedIds.push({ id, label });
        renderPicked();
      }
      pick.value = "";
    });
  }
}

function renderPicked() {
  const wrap = $("#temp-picked");
  if (!wrap) return;
  wrap.innerHTML = tempPickedIds.map(p =>
    `<span class="picked-chip">${esc(p.label)}` +
    `<button type="button" title="Remove" data-id="${esc(p.id)}">✕</button></span>`).join("");
  wrap.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    tempPickedIds = tempPickedIds.filter(x => x.id !== parseInt(b.dataset.id, 10));
    renderPicked();
  }));
}

$("#temp-form")?.addEventListener("submit", async e => {
  e.preventDefault();
  const raw = Object.fromEntries(new FormData(e.target));
  const hours = raw.hours_preset === "custom"
    ? parseFloat(raw.hours) : parseFloat(raw.hours_preset);
  const ids = tempPickedIds.map(p => p.id);
  if (!ids.length) {
    toast("Add at least one patient the guest may open.");
    return;
  }
  try {
    const created = await api("/temp-users", {
      method: "POST",
      body: JSON.stringify({ label: raw.label, hours, patient_ids: ids }),
    });
    e.target.reset();
    tempPickedIds = [];
    renderPicked();
    $("#temp-custom-wrap")?.classList.add("hidden");
    const box = $("#temp-credential");
    $("#temp-credential-text").textContent =
      `Who: ${created.label}\nUsername: ${created.username}\n` +
      `Password: ${created.password}\nExpires: ${created.expires_at.replace("T", " ")}`;
    box.classList.remove("hidden");
    loadTempUsers();
  } catch (err) {
    toast(err.message);
  }
});

/* ------------------------------------------------------------------ helpers */

function debounce(fn, ms) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function deptName(id) {
  const d = deptCache.find(x => x.id === id);
  return d ? d.name : null;
}

function fillTable(table, rows, columns, opts = {}) {
  const thead = table.querySelector("thead") || table.appendChild(document.createElement("thead"));
  const tbody = table.querySelector("tbody") || table.appendChild(document.createElement("tbody"));
  thead.innerHTML = "";
  tbody.innerHTML = "";
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="${esc(columns.length)}" class="muted">Nothing here yet</td></tr>`;
    return;
  }
  thead.innerHTML = `<tr>${columns.map(c => `<th>${esc(c[1])}</th>`).join("")}</tr>`;
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = columns.map(c => {
      const value = c[0] ? row[c[0]] : c[2](row);
      const isDT = (opts.datetime || []).includes(c[0]);
      return `<td>${isDT ? fmtDT(value) : esc(value ?? "—")}</td>`;
    }).join("");
    if (opts.onRowClick) tr.addEventListener("click", () => opts.onRowClick(row));
    tbody.appendChild(tr);
  }
}

function renderList(sel, items, render) {
  const ul = $(sel);
  ul.innerHTML = "";
  if (!items || !items.length) {
    ul.innerHTML = `<li class="muted">Nothing recorded yet</li>`;
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    li.innerHTML = render(item);
    ul.appendChild(li);
  }
}

function esc(value) {
  // Escape text nodes and quoted HTML attributes. Escape ampersands first so
  // the entities introduced below are not double-escaped.
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function fmtDT(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return esc(value);
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function toast(message) {
  let el = $("#toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    Object.assign(el.style, {
      position: "fixed", bottom: "20px", left: "50%",
      transform: "translateX(-50%)", background: "#16283c", color: "#fff",
      padding: "10px 18px", borderRadius: "10px", zIndex: 99,
      boxShadow: "0 8px 30px rgba(0,0,0,.25)", fontSize: "13.5px",
    });
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.style.opacity = "1";
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.style.opacity = "0"; }, 3200);
}

/* ------------------------------------------------------------------ boot */

(async function boot() {
  const saved = localStorage.getItem("medflow.session");
  if (saved) {
    try {
      const session = JSON.parse(saved);
      state.token = session.token;
      state.user = session.user;
      await api("/auth/me");          // fails 401 if the token expired
      enterApp();
      return;
    } catch {
      localStorage.removeItem("medflow.session");
      state.token = null;
    }
  }
  /* no session: the sign-in gate in app.html is already visible */
  const gate = $("#login-gate");
  if (gate) gate.classList.remove("hidden");
})();

/* ================================================================== bell */

let bellTimer = null;

function initBell() {
  const btn = $("#btn-bell");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const panel = $("#notif-panel");
    if (panel.classList.contains("hidden")) {
      panel.classList.remove("hidden");
      loadNotifications();
    } else panel.classList.add("hidden");
  });
  document.addEventListener("click", e => {
    const panel = $("#notif-panel");
    if (!panel || panel.classList.contains("hidden")) return;
    if (!panel.contains(e.target) && e.target !== btn &&
        !btn.contains(e.target)) panel.classList.add("hidden");
  });
  $("#btn-notif-all-read")?.addEventListener("click", async () => {
    try {
      await api("/notifications/read-all", { method: "POST" });
      loadNotifications();
    } catch (err) { toast(err.message); }
  });
  refreshUnread();
  bellTimer = setInterval(refreshUnread, 30000);
}

async function refreshUnread() {
  try {
    const r = await api("/notifications?limit=1");
    const badge = $("#bell-badge");
    if (!badge) return;
    badge.textContent = r.unread > 99 ? "99+" : r.unread || "";
    badge.classList.toggle("hidden", !r.unread);
  } catch { /* bell is best-effort */ }
}

async function loadNotifications() {
  const list = $("#notif-list");
  if (!list) return;
  try {
    const r = await api("/notifications?limit=50");
    list.innerHTML = r.items.length
      ? r.items.map(n => `
        <div class="notif-item ${n.read ? "" : "unread"}" data-id="${esc(n.notification_id)}">
          <div class="n-title">${esc(n.title)}</div>
          ${n.body ? `<div class="n-body">${esc(n.body)}</div>` : ""}
          <div class="n-when">${esc((n.created_at || "").replace("T", " ").slice(0, 16))}
            · ${n.read ? "read — click to mark unread" : "new — click to mark read"}</div>
        </div>`).join("")
      : '<div class="notif-empty">Nothing yet — appointment bookings and account approvals land here.</div>';
    list.querySelectorAll(".notif-item").forEach(el =>
      el.addEventListener("click", async () => {
        const id = parseInt(el.dataset.id, 10);
        const nowRead = !el.classList.contains("unread");
        try {
          await api(`/notifications/${id}/read`, {
            method: "POST", body: JSON.stringify({ read: nowRead })});
          loadNotifications();
          refreshUnread();
        } catch (err) { toast(err.message); }
      }));
    refreshUnread();
  } catch (err) {
    list.innerHTML = `<div class="notif-empty">${esc(err.message)}</div>`;
  }
}

/* ============================================== settings jump list ===== */

const SETTINGS_SECTIONS = [
  ["set-facility", "Facility"], ["set-departments", "Departments"],
  ["set-template", "Record template"], ["set-backups", "Backups"],
  ["set-cloud", "Off-site cloud copy"], ["set-session", "Session & sign-out"],
  ["set-bin", "Recycle bin"], ["set-staff", "Staff & colleagues"],
  ["set-onboarding", "Invites & approvals"], ["set-automation", "Automation rules"],
];

function initSettingsNav() {
  const nav = $("#settings-nav");
  if (!nav) return;
  nav.innerHTML = SETTINGS_SECTIONS
    .map(([id, label]) => {
      const card = document.getElementById(id);
      return card ? `<a href="#${esc(id)}" data-target="${esc(id)}">${esc(label)}</a>` : "";
    }).join("");
  nav.querySelectorAll("a").forEach(a =>
    a.addEventListener("click", e => {
      e.preventDefault();
      document.getElementById(a.dataset.target)
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
  const spy = new IntersectionObserver(entries => {
    entries.forEach(en => {
      const link = nav.querySelector(`a[data-target="${en.target.id}"]`);
      if (!link) return;
      if (en.isIntersecting) {
        nav.querySelectorAll("a").forEach(x => x.classList.remove("here"));
        link.classList.add("here");
      }
    });
  }, { rootMargin: "-20% 0px -65% 0px", threshold: 0 });
  SETTINGS_SECTIONS.forEach(([id]) => {
    const card = document.getElementById(id);
    if (card) spy.observe(card);
  });
}

/* ============================================== invites & approvals === */

$("#invite-form")?.addEventListener("submit", async e => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try {
    const inv = await api("/invites", {
      method: "POST",
      body: JSON.stringify({
        role: data.role, label: data.label || undefined,
        unit_id: data.unit_id ? parseInt(data.unit_id, 10) : undefined,
        days_valid: parseInt(data.days_valid, 10),
      }),
    });
    const out = $("#invite-code-out");
    $("#invite-code-text").textContent =
      `Invite code: ${inv.code}\n` +
      `They enter this on the sign-up page (${inv.role}, valid until ${inv.expires_at.slice(0, 10)})`;
    out.classList.remove("hidden");
    e.target.reset();
    loadInvites();
  } catch (err) { toast(err.message); }
});

async function loadInvites() {
  try {
    const invites = await api("/invites");
    fillTable($("#invites-table"), invites, [
      ["code", "Code"],
      ["role", "Role"],
      ["label", "For"],
      [null, "Valid until", r => (r.expires_at || "").slice(0, 10)],
      [null, "Used", r => `${r.used_count}/${r.max_uses}`],
      [null, "State", r => r.revoked ? "withdrawn"
        : (r.used_count >= r.max_uses ? "used up"
           : (r.expires_at <= new Date().toISOString() ? "expired" : "live"))],
      [null, "", () => ""],
    ]);
    $$("#invites-table tbody tr").forEach((tr, i) => {
      const inv = invites[i];
      if (inv && !inv.revoked && !tr.querySelector("td[colspan]")) {
        const cell = tr.lastElementChild;
        const btn = document.createElement("button");
        btn.className = "btn ghost";
        btn.style.padding = "4px 10px";
        btn.textContent = "Withdraw";
        btn.addEventListener("click", async () => {
          try {
            await api(`/invites/${inv.invite_id}/revoke`, { method: "POST" });
            loadInvites();
          } catch (err) { toast(err.message); }
        });
        cell.appendChild(btn);
      }
    });
  } catch { /* card hidden for non-admins */ }
}

async function loadPendingAccounts() {
  try {
    const pending = await api("/onboarding/pending");
    fillTable($("#pending-table"), pending, [
      ["username", "Username"],
      ["display_name", "Name"],
      [null, "Requested", r => (r.created_at || "").slice(0, 10)],
      [null, "", () => ""],
    ]);
    $$("#pending-table tbody tr").forEach((tr, i) => {
      const u = pending[i];
      if (u && !tr.querySelector("td[colspan]")) {
        const cell = tr.lastElementChild;
        const ok = document.createElement("button");
        ok.className = "btn primary";
        ok.style.padding = "4px 10px";
        ok.textContent = "Approve";
        ok.addEventListener("click", async () => {
          try {
            await api(`/onboarding/${u.user_id}/approve`, {
              method: "POST", body: JSON.stringify({}) });
            toast(`${u.display_name} approved — they can sign in now`, "ok");
            loadPendingAccounts();
            loadStaff();
          } catch (err) { toast(err.message); }
        });
        const no = document.createElement("button");
        no.className = "btn danger";
        no.style.padding = "4px 10px";
        no.style.marginLeft = "6px";
        no.textContent = "Decline";
        no.addEventListener("click", async () => {
          try {
            await api(`/onboarding/${u.user_id}/decline`, {
              method: "POST", body: JSON.stringify({}) });
            loadPendingAccounts();
          } catch (err) { toast(err.message); }
        });
        cell.appendChild(ok);
        cell.appendChild(no);
      }
    });
  } catch { /* hidden for non-admins */ }
}

const origLoadSettings = loadSettings;
loadSettings = async function() {
  await origLoadSettings();
  loadInvites();
  loadPendingAccounts();
};
