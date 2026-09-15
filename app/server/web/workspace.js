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
  api("/health").then(h =>
    $("#facility-label").textContent = `— ${h.facility}`).catch(() => {});
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
    if (btn.dataset.view === "appointments") loadAppointments();
    if (btn.dataset.view === "reports") loadReports();
    if (btn.dataset.view === "settings") loadSettings();
    if (btn.dataset.view === "access") loadTempUsers();
    if (btn.dataset.view === "activity") loadActivity();
  }));

/* sidebar collapse on narrow screens */
const sideBar = document.getElementById("side");
const toggleBtn = document.getElementById("side-collapse");
toggleBtn.addEventListener("click", () => {
  const collapsed = sideBar.style.display === "none";
  sideBar.style.display = collapsed ? "" : "none";
  toggleBtn.textContent = collapsed ? "◀ Hide menu" : "▶ Show menu";
  if (!collapsed && window.innerWidth < 700) toggleBtn.style.display = "none";
  if (collapsed) {
    toggleBtn.style.display = "";
    toggleBtn.style.position = "fixed";
    toggleBtn.style.top = "64px";
    toggleBtn.style.left = "10px";
    toggleBtn.style.zIndex = "30";
    toggleBtn.style.background = "#fff";
    toggleBtn.style.border = "1px solid var(--line)";
    toggleBtn.style.padding = "6px 10px";
    toggleBtn.style.borderRadius = "8px";
  }
});

/* ------------------------------------------------------------------ dashboard */

async function loadDashboard() {
  try {
    const stats = await api("/reports/dashboard");
    $("#st-total").textContent = stats.total_patients;
    $("#st-week").textContent = stats.new_patients_7d;
    $("#st-appts").textContent = stats.appointments_today;
    $("#st-dx").textContent = stats.active_diagnoses;
    $("#st-crit").textContent = stats.critical_labs;
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
    const sel = $("#form-dept");
    if (sel) {
      const current = sel.value;
      sel.innerHTML = '<option value="">— none —</option>' +
        deptCache.filter(d => d.kind !== "organization")
          .map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join("");
      sel.value = current;
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
        ${chart.patient.age != null ? `<span class="tag">${chart.patient.age}y</span>` : ""}
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
    const appts = await api("/appointments?scope=upcoming");
    fillTable($("#appts-table"), appts, [
      ["patient_name", "Patient"],
      ["scheduled_at", "When"],
      ["provider", "Provider"],
      ["reason", "Reason"],
      ["status", "Status"],
    ], { datetime: ["scheduled_at"] });
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
  api("/health").then(h =>
    $("#settings-facility").textContent =
      `${h.facility} — ${h.patients} patient record(s)`).catch(() => {});
  loadBackups();
  loadBin();
  loadCloudBackup();
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

/* ------------------------------------------------------- off-site cloud */

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
    fillTable($("#staff-table"), users, [
      ["username", "Username"],
      ["display_name", "Name"],
      ["role", "Role"],
      [null, "State", r => r.active ? "active" : "disabled"],
      [null, "", () => ""],
    ]);
    $$("#staff-table tbody tr").forEach((tr, i) => {
      const u = users[i];
      if (u && !tr.querySelector("td[colspan]")) {
        const cell = tr.lastElementChild;
        const btn = document.createElement("button");
        btn.className = "btn";
        btn.style.padding = "4px 10px";
        btn.textContent = u.active ? "Disable" : "Enable";
        btn.addEventListener("click", async () => {
          try {
            await api(`/org/users/${u.id}`, {
              method: "PATCH", body: JSON.stringify({ active: !u.active }),
            });
            loadStaff();
          } catch (err) { toast(err.message); }
        });
        cell.appendChild(btn);
      }
    });
  } catch (err) {
    fillTable($("#staff-table"), [], [["", ""]]);
  }
}

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
$("#btn-new-patient").addEventListener("click", () => {
  $("#dlg-patient-title").textContent = "New patient";
  $("#form-patient").reset();
  $("#form-patient-error").classList.add("hidden");
  dlgPatient.showModal();
});

$("#form-patient").addEventListener("submit", async e => {
  if (e.submitter?.value !== "ok") return;
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try {
    const created = await api("/patients", {
      method: "POST", body: JSON.stringify(data),
    });
    dlgPatient.close();
    toast(`Registered ${created.name} (${created.patient_number})`);
    showView("patients");
    loadPatients();
  } catch (err) {
    const box = $("#form-patient-error");
    box.textContent = err.message;
    box.classList.remove("hidden");
  }
});

const dlgAppt = $("#dlg-appointment");
$("#btn-new-appt").addEventListener("click", () => {
  $("#form-appointment").reset();
  $("#form-appointment-error").classList.add("hidden");
  dlgAppt.showModal();
});

$("#form-appointment").addEventListener("submit", async e => {
  if (e.submitter?.value !== "ok") return;
  e.preventDefault();
  const raw = Object.fromEntries(new FormData(e.target));
  try {
    await api(`/appointments?patient_id=${raw.patient_id}`, {
      method: "POST",
      body: JSON.stringify({ ...raw, patient_id: undefined }),
    });
    dlgAppt.close();
    toast("Appointment scheduled");
    loadAppointments();
  } catch (err) {
    const box = $("#form-appointment-error");
    box.textContent = err.message;
    box.classList.remove("hidden");
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

$("#temp-form").addEventListener("submit", async e => {
  e.preventDefault();
  const raw = Object.fromEntries(new FormData(e.target));
  const ids = raw.patient_ids.split(",").map(s => parseInt(s.trim(), 10))
    .filter(n => Number.isInteger(n) && n > 0);
  try {
    const created = await api("/temp-users", {
      method: "POST",
      body: JSON.stringify({ label: raw.label, hours: parseFloat(raw.hours),
                             patient_ids: ids }),
    });
    e.target.reset();
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
    tbody.innerHTML = `<tr><td colspan="${columns.length}" class="muted">Nothing here yet</td></tr>`;
    return;
  }
  thead.innerHTML = `<tr>${columns.map(c => `<th>${c[1]}</th>`).join("")}</tr>`;
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
  return String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
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
