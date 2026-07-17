(() => {
  const { escapeHtml, showToast } = window.PetaNih;
  const $ = (selector) => document.querySelector(selector);
  let organizations = [];
  let alerts = [];

  const safeUrl = (value) => /^https?:\/\//i.test(value || "") ? value : "#";
  const dateTime = (value) => new Date(value).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });

  const renderStats = () => {
    $("#stat-pending").textContent = organizations.filter((item) => item.registration_status === "pending").length;
    $("#stat-verified").textContent = organizations.filter((item) => item.registration_status === "verified").length;
    $("#stat-rejected").textContent = organizations.filter((item) => item.registration_status === "rejected").length;
    $("#stat-alerts").textContent = alerts.length;
  };

  const renderApplications = () => {
    const status = $("#application-status").value;
    const items = organizations.filter((item) => status === "all" || item.registration_status === status);
    $("#application-list").innerHTML = items.map((item) => {
      const documents = Object.entries(item.document_links || {}).map(([kind, url]) => `<a href="${escapeHtml(safeUrl(url))}" target="_blank" rel="noopener">${escapeHtml(kind)}</a>`).join("");
      const statusLabel = { pending: "Menunggu", verified: "Terverifikasi", rejected: "Ditolak" }[item.registration_status] || item.registration_status;
      const canReview = item.registration_status === "pending";
      return `<article class="application-item"><div class="application-item-head"><div><h3>${escapeHtml(item.name)}</h3><div class="application-meta">${escapeHtml(item.applicant_kind === "individual" ? "Relawan individu" : item.type)} · daftar ${item.created_at ? dateTime(item.created_at) : "-"}</div></div><span class="status-badge ${item.verified ? "handled" : ""}">${escapeHtml(statusLabel)}</span></div><div class="application-meta"><b>PIC:</b> ${escapeHtml(item.contact_name)} · ${escapeHtml(item.contact_role)}<br /><b>Kontak:</b> ${escapeHtml(item.email)} · ${escapeHtml(item.phone)}<br /><b>Alamat:</b> ${escapeHtml(item.address)}<br /><b>Area:</b> ${(item.operational_areas || []).map(escapeHtml).join(", ") || "-"}</div><div class="document-links">${documents || "Berkas tidak tersedia"}</div>${item.verification_note ? `<div class="document-note"><b>Catatan admin:</b> ${escapeHtml(item.verification_note)}</div>` : ""}${canReview ? `<div class="verification-controls"><input data-review-note="${item.id}" placeholder="Catatan pemeriksaan" /><button class="button button-outline button-small" data-verify="rejected" data-id="${item.id}" type="button">Tolak</button><button class="button button-primary button-small" data-verify="verified" data-id="${item.id}" type="button">Verifikasi</button></div>` : ""}</article>`;
    }).join("") || '<div class="empty-state">Tidak ada pendaftaran pada status ini.</div>';
  };

  const renderAlerts = () => {
    $("#alert-history").innerHTML = alerts.map((alert) => `<article class="history-item"><strong>${escapeHtml(alert.area_name)}</strong><span>${dateTime(alert.created_at)}</span><p>${escapeHtml(alert.message)} · radius ${alert.radius_km} km · ${alert.delivery_count} penerima</p></article>`).join("") || '<div class="empty-state">Belum ada alert.</div>';
  };

  const load = async () => {
    try {
      const [organizationResponse, alertResponse] = await Promise.all([fetch("/api/admin/organizations?status=all"), fetch("/api/admin/alerts")]);
      if (!organizationResponse.ok || !alertResponse.ok) throw new Error("Gagal memuat data admin");
      organizations = await organizationResponse.json();
      alerts = await alertResponse.json();
      renderStats();
      renderApplications();
      renderAlerts();
    } catch (error) {
      showToast(error.message, 5000);
    }
  };

  $("#application-status").addEventListener("change", renderApplications);
  $("#application-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-verify]");
    if (!button) return;
    const note = document.querySelector(`[data-review-note="${button.dataset.id}"]`)?.value.trim() || "";
    try {
      const response = await fetch(`/api/admin/organizations/${button.dataset.id}/verification`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: button.dataset.verify, note }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Verifikasi gagal");
      showToast(data.verified ? "Lembaga berhasil diverifikasi." : "Pendaftaran ditolak.");
      await load();
    } catch (error) {
      showToast(error.message, 5000);
    }
  });

  $("#admin-alert-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    values.lat = Number(values.lat); values.lon = Number(values.lon); values.radius_km = Number(values.radius_km);
    try {
      const response = await fetch("/api/admin/alerts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Alert gagal dikirim");
      showToast(`Alert dicatat untuk ${data.delivery_count} penerima.`);
      await load();
    } catch (error) {
      showToast(error.message, 5000);
    }
  });

  load();
})();
