/* Public site chrome: hideable sidebar injected on every page. */
"use strict";

(function () {
  const root = document.getElementById("sidebar-root");
  if (!root) return;

  const path = location.pathname;
  const links = [
    ["/", "Home"],
    ["/features", "Features"],
    ["/security", "Security & privacy"],
    ["/guide", "How to use"],
    ["/login", "Sign in"],
    ["/signup", "Create account"],
  ];

  root.innerHTML = `
    <div class="backdrop" id="backdrop"></div>
    <aside class="sidebar" id="sidebar" aria-label="Site menu">
      <button class="side-close" id="side-close" aria-label="Close menu">✕</button>
      <a class="brand" href="/" style="display:flex;align-items:center;gap:10px;text-decoration:none;color:inherit;margin:4px 8px 12px">
        <span class="brand-mark">M</span><strong>MedFlow</strong>
      </a>
      <div class="side-section">Product</div>
      ${links.slice(0, 4).map(([href, label]) =>
        `<a class="side-link" href="${href}">${label}</a>`).join("")}
      <div class="side-section">Account</div>
      ${links.slice(4).map(([href, label]) =>
        `<a class="side-link" href="${href}">${label}</a>`).join("")}
      <div class="spacer"></div>
      <p class="muted small" style="padding:0 12px">Local-first clinic management.
        Your data stays on your machine.</p>
    </aside>`;

  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("backdrop");
  const open = () => { sidebar.classList.add("open"); backdrop.classList.add("show"); };
  const close = () => { sidebar.classList.remove("open"); backdrop.classList.remove("show"); };

  document.querySelectorAll(".menu-btn").forEach((btn) =>
    btn.addEventListener("click", open));
  document.getElementById("side-close").addEventListener("click", close);
  backdrop.addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });

  // highlight current page in the sidebar
  sidebar.querySelectorAll(".side-link").forEach((a) => {
    if (a.getAttribute("href") === path) {
      a.style.background = "#e6f4f2";
      a.style.fontWeight = "600";
    }
  });
})();
