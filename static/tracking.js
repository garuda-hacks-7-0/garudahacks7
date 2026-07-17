(() => {
  const { categoryLabels, escapeHtml, statusLabels, urgencyForSeverity } = window.PetaNih;
  const shell = document.querySelector("#tracking-shell");
  const token = decodeURIComponent(window.location.pathname.split("/").filter(Boolean).pop() || "");
  const statusOrder = { new: 0, verified: 1, in_progress: 2, resolved: 3 };

  const initials = (name) => String(name || "PN").split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  const dateTime = (value) => new Date(value).toLocaleString("id-ID", { dateStyle: "long", timeStyle: "short" });
  const locationOf = (report) => [report.village, report.district, report.regency].filter(Boolean).join(", ") || report.location_label || "Lokasi tidak ditampilkan";
  const isImage = (url) => /\.(png|jpe?g|webp|gif)(\?|$)|images\.unsplash\.com/i.test(url || "");
  const safeUrl = (url) => /^(https?:\/\/|\/)/i.test(url || "") ? url : "#";

  const logo = (organization) => organization.logo_url
    ? `<span class="organization-logo"><img src="${escapeHtml(safeUrl(organization.logo_url))}" alt="Logo ${escapeHtml(organization.name)}" /></span>`
    : `<span class="organization-logo">${escapeHtml(initials(organization.name))}</span>`;

  const documents = (urls) => {
    if (!urls?.length) return "";
    return `<div class="tracking-docs">${urls.map((url, index) => isImage(url) ? `<a href="${escapeHtml(safeUrl(url))}" target="_blank" rel="noopener"><img src="${escapeHtml(safeUrl(url))}" alt="Dokumentasi penanganan ${index + 1}" loading="lazy" referrerpolicy="no-referrer" /></a>` : `<a class="document-note" href="${escapeHtml(safeUrl(url))}" target="_blank" rel="noopener">Buka dokumentasi ${index + 1}</a>`).join("")}</div>`;
  };

  const organizationRow = (organization) => `<div class="organization-row">${logo(organization)}<div><strong>${escapeHtml(organization.name)}</strong><span>${escapeHtml(organization.contact_role || organization.type)}</span></div></div>`;

  const render = (report) => {
    const urgency = urgencyForSeverity(report.severity);
    const currentIndex = statusOrder[report.response_status] ?? 0;
    const progress = ["Laporan masuk", "Terverifikasi", "Sedang ditangani", "Selesai"].map((label, index) => `<div class="progress-step ${index < currentIndex ? "done" : index === currentIndex ? "current" : ""}">${label}</div>`).join("");
    const evidence = (report.evidence_urls || []).map((url, index) => `<a href="${escapeHtml(safeUrl(url))}" target="_blank" rel="noopener"><img src="${escapeHtml(safeUrl(url))}" alt="Bukti awal ${index + 1}" loading="lazy" referrerpolicy="no-referrer" /></a>`).join("");
    const timeline = [
      `<article class="timeline-item"><div class="timeline-head"><strong>Laporan diterima</strong><time>${dateTime(report.created_at)}</time></div><p>Laporan sudah tersimpan dan masuk antrean verifikasi.</p></article>`,
      ...(report.updates || []).map((update) => `<article class="timeline-item"><div class="timeline-head"><strong>${escapeHtml(statusLabels[update.status] || update.status)}</strong><time>${dateTime(update.created_at)}</time></div><p>${escapeHtml(update.note || "Status laporan diperbarui.")}</p>${organizationRow(update.organization)}${documents(update.documentation_urls)}</article>`),
    ].join("");
    const organization = report.responsible_organization;
    const phone = String(organization?.phone || "").replace(/[^+\d]/g, "");
    const contact = organization ? `<div class="tracking-card"><h2>Penanggung jawab saat ini</h2>${organizationRow(organization)}<div class="contact-list">${organization.contact_name ? `<span><b>Kontak resmi:</b> ${escapeHtml(organization.contact_name)} · ${escapeHtml(organization.contact_role)}</span>` : ""}${phone ? `<a href="tel:${escapeHtml(phone)}">${escapeHtml(organization.phone)}</a>` : ""}${organization.email ? `<a href="mailto:${escapeHtml(organization.email)}">${escapeHtml(organization.email)}</a>` : ""}${organization.website ? `<a href="${escapeHtml(safeUrl(organization.website))}" target="_blank" rel="noopener">Website lembaga</a>` : ""}</div><p class="privacy-copy">Kontak yang ditampilkan adalah kanal resmi lembaga. Nomor pribadi pelapor dan relawan individu tetap dirahasiakan.</p></div>` : `<div class="tracking-card"><h2>Penanggung jawab</h2><p class="privacy-copy">Belum ada lembaga yang ditugaskan. Update akan muncul di sini setelah laporan diverifikasi.</p></div>`;
    shell.innerHTML = `<div class="tracking-hero"><div><p class="tracking-eyebrow">Tracking laporan ${escapeHtml(report.tracking_id)}</p><h1 class="tracking-title">Perkembangan bantuanmu</h1><p class="tracking-subtitle">Diperbarui ${dateTime(report.updated_at)}. Perubahan penting tetap dikirim lewat WhatsApp.</p></div><span class="urgency-badge urgency-${urgency.key}">${urgency.label}</span></div><div class="tracking-card"><div class="progress-track">${progress}</div><h2>Ringkasan laporan</h2><p class="tracking-description">${escapeHtml(report.ai_summary || report.incident_description)}</p><div class="tracking-facts"><div class="tracking-fact"><span>Status saat ini</span><strong>${escapeHtml(statusLabels[report.response_status] || report.response_status)}</strong></div><div class="tracking-fact"><span>Lokasi</span><strong>${escapeHtml(locationOf(report))}</strong></div><div class="tracking-fact"><span>Jenis kejadian</span><strong>${escapeHtml(categoryLabels[report.category] || report.category)}</strong></div><div class="tracking-fact"><span>Kebutuhan</span><strong>${(report.needs || []).map(escapeHtml).join(", ") || "Belum disebutkan"}</strong></div></div>${evidence ? `<h2 style="margin-top:24px">Bukti awal</h2><div class="evidence-gallery">${evidence}</div>` : ""}</div><div class="tracking-grid" style="margin-top:24px"><section class="tracking-card"><h2>Riwayat penanganan</h2><div class="timeline">${timeline}</div></section><aside>${contact}<div class="tracking-card"><h2>Tentang halaman ini</h2><p class="privacy-copy">Link ini bersifat unik. Jangan sebarkan jika laporan memuat foto atau informasi lokasi yang sensitif.</p></div></aside></div>`;
    document.title = `${report.tracking_id} — Status Laporan Peta.ni`;
  };

  const load = async () => {
    try {
      const response = await fetch(`/api/public/reports/${encodeURIComponent(token)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Laporan tidak ditemukan");
      render(data);
    } catch (error) {
      shell.innerHTML = `<div class="empty-state"><strong>Link laporan tidak valid.</strong><br />${escapeHtml(error.message)}</div>`;
    }
  };

  load();
  window.setInterval(load, 15000);
})();
