(() => {
  const ROLE_KEY = "petani_demo_role";
  const SESSION_NAME_KEY = "petani_demo_name";

  const escapeHtml = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");

  const isAdmin = () => localStorage.getItem(ROLE_KEY) === "admin";
  const isResponder = () => ["responder", "admin"].includes(localStorage.getItem(ROLE_KEY));

  const setResponderSession = (name = "Relawan") => {
    localStorage.setItem(ROLE_KEY, "responder");
    localStorage.setItem(SESSION_NAME_KEY, name);
  };

  const setAdminSession = (name = "Admin") => {
    localStorage.setItem(ROLE_KEY, "admin");
    localStorage.setItem(SESSION_NAME_KEY, name);
  };

  const clearSession = () => {
    localStorage.removeItem(ROLE_KEY);
    localStorage.removeItem(SESSION_NAME_KEY);
  };

  const urgencyForRisk = (risk) => {
    const score = Number(risk || 0);
    if (score >= 0.75) return { key: "high", label: "Urgensi Tinggi" };
    if (score >= 0.55) return { key: "medium", label: "Urgensi Sedang" };
    return { key: "low", label: "Urgensi Rendah" };
  };

  const urgencyForSeverity = (severity) => {
    if (["critical", "high"].includes(severity)) return { key: "high", label: "Urgensi Tinggi" };
    if (severity === "medium") return { key: "medium", label: "Urgensi Sedang" };
    return { key: "low", label: "Urgensi Rendah" };
  };

  const statusLabels = {
    new: "Menunggu verifikasi AI",
    verified: "Terverifikasi",
    in_progress: "Sedang ditangani",
    resolved: "Selesai",
    rejected: "Perlu diperiksa",
  };

  const categoryLabels = {
    flood: "Banjir",
    drought: "Kekeringan",
    crop_damage: "Kerusakan tanaman",
    crop_pest: "Hama tanaman",
    storm: "Angin kencang",
    fire: "Kebakaran lahan",
    landslide: "Longsor",
    unknown: "Dampak pertanian",
  };

  let toastTimer;
  const showToast = (message, timeout = 3200) => {
    const toast = document.querySelector("#toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("visible"), timeout);
  };

  const mountShell = () => {
    const responder = isResponder();
    const admin = isAdmin();
    document.querySelectorAll("[data-responder-only]").forEach((node) => {
      node.hidden = !responder;
    });
    document.querySelectorAll("[data-admin-only]").forEach((node) => {
      node.hidden = !admin;
    });

    document.querySelectorAll("[data-session-link]").forEach((link) => {
      if (admin) {
        link.textContent = "Panel Admin";
        link.href = "/admin";
      } else if (responder) {
        link.textContent = "Mode Relawan";
        link.href = "/reports";
      } else {
        link.textContent = "Contribute Now";
        link.href = "/login";
      }
    });

    document.querySelectorAll("[data-logout]").forEach((button) => {
      button.hidden = !responder;
      button.addEventListener("click", () => {
        clearSession();
        window.location.href = "/map";
      });
    });

    const header = document.querySelector(".site-header");
    const menuButton = document.querySelector(".mobile-menu-button");
    menuButton?.addEventListener("click", () => {
      const isOpen = header?.classList.toggle("menu-open");
      menuButton.setAttribute("aria-expanded", String(Boolean(isOpen)));
    });

    document.querySelectorAll("[data-whatsapp-link]").forEach((link) => {
      link.href = "https://wa.me/14155238886";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    });
  };

  window.PetaNih = {
    ROLE_KEY,
    SESSION_NAME_KEY,
    categoryLabels,
    clearSession,
    escapeHtml,
    isAdmin,
    isResponder,
    setAdminSession,
    setResponderSession,
    showToast,
    statusLabels,
    urgencyForRisk,
    urgencyForSeverity,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountShell);
  } else {
    mountShell();
  }
})();
