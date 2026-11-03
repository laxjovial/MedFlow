/* Login + signup pages: password forms, Google button, session storage.

   If you already have a live session (say you reached here from browser
   history or a bookmark), the page notices and signs you straight through
   to your workspace — no need to type anything again. */
"use strict";

const $ = (sel) => document.querySelector(sel);

async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    "Content-Type": "application/json",
    ...options,
    headers: { "Content-Type": "application/json", "X-MedFlow-Web-Session": "1", ...(options.headers || {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body.detail || body.error || {};
    throw new Error(typeof detail === "string" ? detail : detail.message || "Request failed");
  }
  return body;
}

function saveSession() {
  localStorage.removeItem("medflow.session");
  localStorage.removeItem("medflow.remember");
  location.href = "/app";
}

(async function skipIfSignedIn() {
  localStorage.removeItem("medflow.session");
  try {
    const res = await fetch("/api/auth/me", {
      headers: { "X-MedFlow-Web-Session": "1" },
      credentials: "same-origin",
    });
    if (res.ok) location.replace("/app");
  } catch { /* remain on sign-in form */ }
})();

/* ------------------------------------------------------------ password */

const loginForm = $("#login-form");
if (loginForm) {
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const box = $("#login-error");
    box.classList.add("hidden");
    try {
      const data = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: $("#login-user").value.trim(),
                               password: $("#login-pass").value,
                               remember: $("#login-remember").checked }),
      });
      saveSession();
    } catch (err) {
      box.textContent = err.message;
      box.classList.remove("hidden");
    }
  });
}

const signupForm = $("#signup-form");
if (signupForm) {
  signupForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const box = $("#signup-error");
    box.classList.add("hidden");
    try {
      const invite = $("#su-invite")?.value.trim() || null;
      const data = await api("/auth/signup", {
        method: "POST",
        body: JSON.stringify({
          username: $("#su-user").value.trim(),
          display_name: $("#su-name").value.trim(),
          email: $("#su-email").value.trim() || null,
          password: $("#su-pass").value,
          invite_code: invite || undefined,
        }),
      });
      if (data.pending) {
        // invited accounts wait for an administrator's approval
        box.textContent = data.user?.message ||
          "Account created — an administrator still needs to approve it.";
        box.classList.remove("hidden");
        box.classList.add("ok");
        return;
      }
      saveSession(data);
    } catch (err) {
      box.textContent = err.message;
      box.classList.remove("hidden");
    }
  });
}

/* -------------------------------------------------------------- google */

async function loadGoogle() {
  try {
    const config = await api("/auth/config");
    if (!config.google_enabled) {
      const note = $("#google-note");
      if (note) note.classList.remove("hidden");
      const btn = $("#google-btn");
      if (btn) btn.disabled = true;
      return;
    }
    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://accounts.google.com/gsi/client";
      script.onload = resolve;
      script.onerror = () => reject(new Error("gsi"));
      document.head.appendChild(script);
    });
    const client = await api("/auth/google/client-id");
    google.accounts.id.initialize({
      client_id: client.client_id,
      callback: async (response) => {
        try {
          const data = await api("/auth/google", {
            method: "POST",
            body: JSON.stringify({ id_token: response.credential }),
          });
          saveSession(data);
        } catch (err) {
          const box = $("#login-error") || $("#signup-error");
          box.textContent = err.message;
          box.classList.remove("hidden");
        }
      },
    });
    google.accounts.id.renderButton($("#google-btn"), {});
    $("#google-btn").style.display = "none";  // replaced by the rendered one
  } catch (err) {
    const note = $("#google-note");
    if (note) note.classList.remove("hidden");
    const btn = $("#google-btn");
    if (btn) btn.disabled = true;
  }
}

loadGoogle();
