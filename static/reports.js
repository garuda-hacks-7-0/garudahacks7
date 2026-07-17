(() => {
  const { categoryLabels, escapeHtml, showToast, statusLabels, urgencyForSeverity } = window.PetaNih;
  const $ = (selector) => document.querySelector(selector);
  let allReports = [];

  const provinceOf = (report) => {
    const location = `${report.regency || ""} ${report.location_label || ""}`.toLowerCase();
    return location.includes("depok") ? "Jawa Barat" : "Jawa Tengah";
  };

  const locationOf = (report) => [report.village, report.district, report.regency].filter(Boolean).join(", ") || report.location_label || "Lokasi perlu diverifikasi";

  const titleOf = (report) => {
    const category = categoryLabels[report.category] || "Dampak pertanian";
    const place = report.village || report.district || report.regency || "lokasi laporan";
    return `${category} ${place}`;
  };

  const reportCard = (report) => {
    const urgency = urgencyForSeverity(report.severity);
    const cover = report.evidence_urls?.[0] || report.image_url || "/static/assets/report-cover.png";
    const needs = (report.needs || []).slice(0, 3).map((need) => `<span class="need-chip">${escapeHtml(need)}</span>`).join("") || '<span class="need-chip">Kebutuhan belum disebutkan</span>';
    return `
      <article class="report-card">
        <div class="report-cover"><img src="${escapeHtml(cover)}" alt="Bukti ${escapeHtml(titleOf(report))}" loading="lazy" referrerpolicy="no-referrer" /><span class="urgency-badge urgency-${urgency.key}">${urgency.label}</span></div>
        <div class="report-card-body">
          <h2>${escapeHtml(titleOf(report))}</h2>
          <div class="report-location"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg><span>${escapeHtml(locationOf(report))}</span></div>
          <div class="need-chips">${needs}</div>
          <div class="report-card-actions"><button class="button button-soft button-small" type="button" data-report-detail="${report.id}">Lihat detail</button><a class="button button-outline button-small" href="/map?lat=${encodeURIComponent(report.lat ?? "")}&lon=${encodeURIComponent(report.lon ?? "")}">Buka peta</a></div>
        </div>
      </article>`;
  };

  const selectedValues = (name) => Array.from(document.querySelectorAll(`input[name="${name}"]:checked`)).map((input) => input.value);

  const render = () => {
    const query = $("#report-search").value.trim().toLowerCase();
    const province = $("#province").value;
    const urgencies = selectedValues("urgency");
    const needs = selectedValues("need");
    const filtered = allReports.filter((report) => {
      const haystack = `${titleOf(report)} ${locationOf(report)} ${report.ai_summary || ""} ${(report.needs || []).join(" ")}`.toLowerCase();
      const urgency = urgencyForSeverity(report.severity).key;
      return (!query || haystack.includes(query))
        && (province === "all" || provinceOf(report) === province)
        && (!urgencies.length || urgencies.includes(urgency))
        && (!needs.length || needs.some((need) => (report.needs || []).includes(need)));
    });
    $("#report-count").textContent = `${filtered.length} laporan ditemukan`;
    $("#reports-grid").innerHTML = filtered.map(reportCard).join("") || '<div class="empty-state"><strong>Tidak ada laporan yang sesuai.</strong><br />Coba ubah atau reset filter.</div>';
  };

  const confidenceRows = (report) => {
    const labels = { evidence: "Foto bukti", location: "Lokasi", village: "Desa/Kelurahan", district: "Kecamatan", regency: "Kota/Kabupaten", description: "Deskripsi", is_local_farmer: "Petani setempat", needs: "Bantuan", category: "Jenis kejadian", severity: "Keparahan", medical_needed: "Kebutuhan medis" };
    return Object.entries(report.field_confidences || {}).filter(([key]) => labels[key]).map(([key, value]) => `<span>${labels[key]}</span><strong>${Math.round(Number(value) * 100)}%</strong>`).join("");
  };

  const openDetail = (report) => {
    const urgency = urgencyForSeverity(report.severity);
    const profile = report.farmer_profile || {};
    const images = (report.evidence_urls || []).map((url, index) => `<img src="${escapeHtml(url)}" alt="Bukti ${index + 1}" loading="lazy" referrerpolicy="no-referrer" />`).join("");
    const needs = (report.needs || []).map((need) => `<span class="need-chip">${escapeHtml(need)}</span>`).join("") || '<span class="need-chip">Belum disebutkan</span>';
    const critique = (report.readiness_critique || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    $("#dialog-title").textContent = report.reporter_alias;
    $("#dialog-body").innerHTML = `
      <span class="urgency-badge urgency-${urgency.key}">${urgency.label}</span>
      ${images ? `<div class="mini-report-images">${images}</div>` : ""}
      <section class="panel-section"><h3>${escapeHtml(titleOf(report))}</h3><p>${escapeHtml(report.ai_summary || report.incident_description || report.text)}</p></section>
      <div class="info-block"><b>Status</b><br />${escapeHtml(statusLabels[report.response_status] || report.response_status)}</div>
      <div class="info-block"><b>Lokasi</b><br />${escapeHtml(locationOf(report))}<br /><span>${escapeHtml(report.location_verification_status)}</span></div>
      <div class="info-block"><b>Profil petani</b><br />Petani/penggarap: ${profile.is_farmer == null ? "belum diketahui" : profile.is_farmer ? "ya" : "tidak"} · Petani setempat: ${profile.is_local_farmer == null ? "belum diketahui" : profile.is_local_farmer ? "ya" : "tidak"}</div>
      <div class="info-block"><b>Bantuan dibutuhkan</b><div class="need-chips">${needs}</div></div>
      <div class="info-block"><b>Confidence kesiapan ${report.readiness_score}%</b><br />Bukti terverifikasi ${report.verified_evidence_count}/${report.evidence_target}${critique ? `<ul>${critique}</ul>` : ""}</div>
      <div class="info-block"><b>Confidence per field</b><div class="confidence-grid">${confidenceRows(report) || "Belum tersedia"}</div></div>
      <div class="modal-actions"><a class="button button-primary button-small" href="/map?lat=${encodeURIComponent(report.lat ?? "")}&lon=${encodeURIComponent(report.lon ?? "")}">Lihat di peta</a></div>`;
    $("#report-dialog").showModal();
  };

  $("#reports-grid").addEventListener("click", (event) => {
    const button = event.target.closest("[data-report-detail]");
    if (!button) return;
    const report = allReports.find((item) => item.id === Number(button.dataset.reportDetail));
    if (report) openDetail(report);
  });

  $("#close-report-dialog").addEventListener("click", () => $("#report-dialog").close());
  $("#report-dialog").addEventListener("click", (event) => {
    if (event.target === $("#report-dialog")) $("#report-dialog").close();
  });

  [$("#report-search"), $("#province"), ...document.querySelectorAll('input[name="urgency"], input[name="need"]')].forEach((control) => control.addEventListener("input", render));

  $("#clear-filters").addEventListener("click", () => {
    $("#report-search").value = "";
    $("#province").value = "all";
    document.querySelectorAll('input[name="urgency"], input[name="need"]').forEach((input) => { input.checked = false; });
    render();
  });

  fetch("/api/reports?view=responder")
    .then((response) => {
      if (!response.ok) throw new Error("Gagal memuat laporan");
      return response.json();
    })
    .then((reports) => {
      allReports = reports;
      render();
    })
    .catch((error) => {
      $("#report-count").textContent = "Data tidak tersedia";
      $("#reports-grid").innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
      showToast(error.message);
    });
})();
