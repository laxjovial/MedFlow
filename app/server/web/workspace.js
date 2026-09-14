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

async function login(username, password) {
  const data = await api("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  state.token = data.token;
  state.user = data.user;
  localStorage.setItem("medflow.session",
    JSON.stringify({ token: data.token, user: data.user }));
  enterApp();
}

function enterApp() {
  $("#login-gate").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#whoami").textContent =
    `${state.user.display_name} · ${state.user.role}` +
    (state.user.temporary ? " (temporary)" : "");
  const perms = new Set(state.user.permissions || []);
  const temporary = !!state.user.temporary;
  $("#btn-new-patient").classList.toggle("hidden", !perms.has("patients.create"));
  $("#btn-delete-patient").classList.toggle("hidden", !perms.has("patients.delete"));
  $("#btn-new-appt").classList.toggle("hidden", !perms.has("appointments.manage"));
  $("#nav-access").classList.toggle("hidden", !perms.has("users.manage"));
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

/* ------------------------------------------------------------------ patients */

let searchTimer = null;
$("#patient-search").addEventListener("input", e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadPatients(e.target.value), 200);
});

async function loadPatients(query = "") {
  try {
    state.patients = await api(`/patients?q=${encodeURIComponent(query)}`);
    fillTable($("#patients-table"), state.patients, [
      ["patient_number", "No"],
      ["name", "Name"],
      ["age", "Age"],
      ["sex", "Sex"],
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
  $("#login-view").classList.remove("hidden");
})();

$("#login-form").addEventListener("submit", async e => {
  e.preventDefault();
  const box = $("#login-error");
  box.classList.add("hidden");
  try {
    await login($("#login-user").value.trim(), $("#login-pass").value);
  } catch (err) {
    box.textContent = err.message || "Sign-in failed";
    box.classList.remove("hidden");
  }
});
