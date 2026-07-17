(() => {
  const { categoryLabels, escapeHtml, isResponder, showToast, statusLabels, urgencyForRisk } = window.PetaNih;
  const responder = isResponder();
  const view = responder ? "responder" : "public";
  const $ = (selector) => document.querySelector(selector);

  const fallbackLocation = { lat: -6.9218, lon: 110.5157, label: "Posisi demo Sayung" };
  let currentLocation = fallbackLocation;
  let regions = [];
  let selectedRegionId = null;
  let organizations = [];
  let statusTimer;

  const map = L.map("map", { zoomControl: false }).setView([-6.9, 110.62], 9);
  L.control.zoom({ position: "bottomright" }).addTo(map);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);
  const regionLayer = L.layerGroup().addTo(map);
  const userLayer = L.layerGroup().addTo(map);

  const riskColor = (risk) => {
    const key = urgencyForRisk(risk).key;
    return key === "high" ? "#de0000" : key === "medium" ? "#f2b90b" : "#347428";
  };

  const showStatus = (message, timeout = 2400) => {
    const node = $("#map-status");
    node.textContent = message;
    node.classList.add("visible");
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => node.classList.remove("visible"), timeout);
  };

  const api = async (url, options = {}) => {
    const response = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Permintaan gagal");
    return data;
  };

  const getQuery = () => {
    const params = new URLSearchParams({
      view,
      category: $("#category").value,
      hours: $("#hours").value,
    });
    if (responder) {
      params.set("urgency", $("#urgency").value);
      params.set("lat", currentLocation.lat);
      params.set("lon", currentLocation.lon);
      params.set("max_distance_km", $("#distance").value);
    }
    return params.toString();
  };

  const categorySummary = (counts) => {
    const entries = Object.entries(counts || {}).sort((a, b) => b[1] - a[1]);
    if (!entries.length) return "Jenis kejadian belum teridentifikasi";
    return entries.map(([key, count]) => `${categoryLabels[key] || key} (${count})`).join(", ");
  };

  const needsList = (needs) => {
    const entries = Object.entries(needs || {}).sort((a, b) => b[1] - a[1]);
    if (!entries.length) return '<li>Kebutuhan belum disebutkan dalam laporan.</li>';
    return entries.map(([need, count]) => `<li>${escapeHtml(need)}${count > 1 ? ` · ${count} laporan` : ""}</li>`).join("");
  };

  const confidenceRows = (report) => {
    const labels = {
      evidence: "Foto bukti",
      location: "Lokasi",
      village: "Desa/Kelurahan",
      district: "Kecamatan",
      regency: "Kota/Kabupaten",
      description: "Deskripsi",
      is_local_farmer: "Petani setempat",
      needs: "Bantuan",
      category: "Jenis kejadian",
      severity: "Keparahan",
      medical_needed: "Kebutuhan medis",
    };
    return Object.entries(report.field_confidences || {})
      .filter(([key]) => labels[key])
      .map(([key, value]) => `<span>${labels[key]}</span><strong>${Math.round(Number(value) * 100)}%</strong>`)
      .join("");
  };

  const reportCard = (report) => {
    const handled = report.response_status !== "new" && report.response_status !== "rejected";
    const images = (report.evidence_urls || [])
      .slice(0, 2)
      .map((url, index) => `<img src="${escapeHtml(url)}" alt="Bukti laporan ${index + 1}" loading="lazy" referrerpolicy="no-referrer" />`)
      .join("");
    const location = [report.village, report.district, report.regency].filter(Boolean).join(" · ") || report.location_label || "Belum lengkap";
    const profile = report.farmer_profile || {};
    const needs = (report.needs || []).map((need) => `<span class="need-chip">${escapeHtml(need)}</span>`).join("") || '<span class="need-chip">Belum disebutkan</span>';
    const critique = (report.readiness_critique || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    return `
      <article class="mini-report">
        <div class="mini-report-head">
          <strong>${escapeHtml(report.reporter_alias)}</strong>
          <span class="status-badge ${handled ? "handled" : ""}">${escapeHtml(statusLabels[report.response_status] || report.response_status)}</span>
        </div>
        ${images ? `<div class="mini-report-images">${images}</div>` : ""}
        <p>${escapeHtml(report.ai_summary || report.incident_description || report.text)}</p>
        <div class="need-chips">${needs}</div>
        <div class="report-extra" id="report-extra-${report.id}">
          <div class="info-block"><b>Lokasi</b><br />${escapeHtml(location)}<br /><span>${escapeHtml(report.location_verification_status)}</span></div>
          <div class="info-block"><b>Profil petani</b><br />Petani/penggarap: ${profile.is_farmer == null ? "belum diketahui" : profile.is_farmer ? "ya" : "tidak"} · Petani setempat: ${profile.is_local_farmer == null ? "belum diketahui" : profile.is_local_farmer ? "ya" : "tidak"}</div>
          <div class="info-block"><b>Confidence kesiapan ${report.readiness_score}%</b><br />Bukti terverifikasi ${report.verified_evidence_count}/${report.evidence_target}${critique ? `<ul>${critique}</ul>` : ""}</div>
          <div class="info-block"><b>Confidence per field</b><div class="confidence-grid">${confidenceRows(report) || "Belum tersedia"}</div></div>
          <div class="info-block"><b>Bantuan dibutuhkan</b><div class="need-chips">${needs}</div></div>
        </div>
        <div class="mini-actions">
          <button class="button button-soft button-small" type="button" data-toggle-report="${report.id}">Detail laporan</button>
          <button class="button button-primary button-small" type="button" data-update-report="${report.id}">Update status</button>
        </div>
      </article>`;
  };

  const contactCards = (contacts) => {
    if (!contacts?.length) return '<p>Belum ada kontak kantor desa dalam radius 50 km.</p>';
    return contacts
      .map((contact) => {
        const phone = String(contact.phone || "").replace(/[^+\d]/g, "");
        const wa = phone.replace(/^\+/, "").replace(/^0/, "62");
        return `<div class="contact-card"><b>${escapeHtml(contact.name)}</b><br /><span>${escapeHtml(contact.distance_km)} km · ${escapeHtml(contact.phone || "nomor belum tersedia")}</span>${phone ? `<div class="mini-actions"><a class="button button-outline button-small" href="tel:${phone}">Telepon kantor</a>${wa.startsWith("62") ? `<a class="button button-primary button-small" href="https://wa.me/${wa}" target="_blank" rel="noopener">WhatsApp kantor</a>` : ""}</div>` : ""}</div>`;
      })
      .join("");
  };

  const renderPanel = (region) => {
    if (!region) return;
    selectedRegionId = region.id;
    const urgency = urgencyForRisk(region.risk_score);
    const handled = (region.progress?.verified || 0) + (region.progress?.in_progress || 0) + (region.progress?.resolved || 0);
    const reports = responder
      ? `<section class="panel-section"><h3>Laporan</h3><div class="report-list-panel">${(region.reports || []).map(reportCard).join("") || "<p>Belum ada laporan.</p>"}</div></section>`
      : "";
    const responderTools = responder
      ? `<section class="panel-section"><h3>Kontak kantor desa terdekat</h3>${contactCards(region.nearest_contacts)}</section><section class="panel-section"><button class="button button-outline button-small" type="button" data-autp-region="${region.id}">Kirim reminder AUTP</button></section>`
      : "";

    $("#panel-title").textContent = region.name;
    $("#panel-content").innerHTML = `
      <span class="urgency-badge urgency-${urgency.key}">${urgency.label}</span>
      <section class="panel-section">
        <h3>Ringkasan</h3>
        <ul>
          <li>${region.report_count} laporan terhimpun</li>
          <li>${escapeHtml(region.last_summary || "Ringkasan belum tersedia")}</li>
          <li>${escapeHtml(categorySummary(region.category_counts))}</li>
          ${responder ? `<li>${handled} laporan sudah masuk proses penanganan</li>` : ""}
        </ul>
      </section>
      <section class="panel-section"><h3>Kebutuhan</h3><ul>${needsList(region.aggregate_needs)}</ul></section>
      ${responderTools}
      ${reports}`;
    $("#detail-panel").classList.add("open");
  };

  const drawMap = () => {
    regionLayer.clearLayers();
    regions.forEach((region) => {
      const color = riskColor(region.risk_score);
      const marker = L.circleMarker([region.lat, region.lon], {
        radius: 14 + Math.min(region.report_count * 1.4, 18),
        color: "rgba(255,255,255,.92)",
        weight: 4,
        fillColor: color,
        fillOpacity: 0.88,
      }).addTo(regionLayer);
      marker.bindTooltip(`${escapeHtml(region.name)} · ${urgencyForRisk(region.risk_score).label}`, { direction: "top", offset: [0, -10] });
      marker.on("click", () => renderPanel(region));
    });
  };

  const refresh = async ({ quiet = false } = {}) => {
    try {
      if (!quiet) showStatus("Memuat laporan terbaru…", 10000);
      if (responder) $("#distance-label").textContent = `${Number($("#distance").value).toLocaleString("id-ID")} km`;
      regions = await api(`/api/regions?${getQuery()}`);
      drawMap();
      if (selectedRegionId) {
        const selected = regions.find((region) => region.id === selectedRegionId);
        if (selected) renderPanel(selected);
        else $("#detail-panel").classList.remove("open");
      }
      showStatus(`${regions.length} wilayah diperbarui`, 1800);
    } catch (error) {
      showStatus(`Gagal memuat: ${error.message}`, 6000);
    }
  };

  const setLocation = (location) => {
    currentLocation = location;
    userLayer.clearLayers();
    if (responder) {
      L.circleMarker([location.lat, location.lon], { radius: 7, color: "#fff", weight: 3, fillColor: "#023a2e", fillOpacity: 1 })
        .addTo(userLayer)
        .bindTooltip(location.label);
    }
  };

  $("#filter-toggle").addEventListener("click", () => {
    const open = $("#filter-popover").classList.toggle("open");
    $("#filter-toggle").setAttribute("aria-expanded", String(open));
  });

  $("#apply-filter").addEventListener("click", () => {
    $("#filter-popover").classList.remove("open");
    $("#filter-toggle").setAttribute("aria-expanded", "false");
    refresh();
  });

  $("#close-panel").addEventListener("click", () => {
    selectedRegionId = null;
    $("#detail-panel").classList.remove("open");
  });

  map.on("click", (event) => {
    if (!event.originalEvent.target.closest?.(".leaflet-interactive")) {
      selectedRegionId = null;
      $("#detail-panel").classList.remove("open");
    }
  });

  $("#map-search").addEventListener("input", (event) => {
    const query = event.target.value.trim().toLowerCase();
    if (!query) return;
    const match = regions.find((region) => region.name.toLowerCase().includes(query));
    if (match) {
      map.flyTo([match.lat, match.lon], Math.max(map.getZoom(), 11), { duration: 0.5 });
      renderPanel(match);
    }
  });

  $("#panel-content").addEventListener("click", async (event) => {
    const toggle = event.target.closest("[data-toggle-report]");
    if (toggle) {
      $("#report-extra-" + toggle.dataset.toggleReport)?.classList.toggle("open");
      toggle.textContent = toggle.textContent === "Tutup detail" ? "Detail laporan" : "Tutup detail";
      return;
    }
    const update = event.target.closest("[data-update-report]");
    if (update) {
      $("#status-report-id").value = update.dataset.updateReport;
      $("#status-dialog").showModal();
      return;
    }
    const autp = event.target.closest("[data-autp-region]");
    if (autp) {
      try {
        const result = await api(`/api/regions/${autp.dataset.autpRegion}/autp-reminder`, { method: "POST" });
        showToast(`Reminder AUTP dicatat untuk ${result.matched_reporters} petani.`);
      } catch (error) {
        showToast(error.message);
      }
    }
  });

  document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => $("#status-dialog").close()));
  $("#status-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const organization = organizations.find((item) => item.id === Number($("#organization").value)) || organizations[0];
    if (!organization) return showToast("Organisasi demo belum tersedia.");
    try {
      const result = await api(`/api/reports/${$("#status-report-id").value}/status`, {
        method: "POST",
        body: JSON.stringify({ status: $("#new-status").value, organization_id: organization.id, note: $("#status-note").value.trim() }),
      });
      $("#status-dialog").close();
      $("#status-note").value = "";
      showToast(`Status diperbarui oleh ${result.organization_name}.`);
      await refresh({ quiet: true });
    } catch (error) {
      showToast(error.message);
    }
  });

  if (responder) {
    $("#use-location").addEventListener("click", () => {
      if (!navigator.geolocation) {
        setLocation(fallbackLocation);
        return refresh();
      }
      showStatus("Mengambil lokasi Anda…", 10000);
      navigator.geolocation.getCurrentPosition(
        (position) => {
          setLocation({ lat: position.coords.latitude, lon: position.coords.longitude, label: "Lokasi responder" });
          map.flyTo([position.coords.latitude, position.coords.longitude], 11);
          refresh();
        },
        () => {
          setLocation(fallbackLocation);
          showToast("Izin lokasi ditolak. Peta memakai posisi demo Sayung.");
          refresh();
        },
        { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 },
      );
    });

    $("#send-demo").addEventListener("click", async () => {
      try {
        showStatus("Membuat laporan demo…", 10000);
        await api("/demo/reports", {
          method: "POST",
          body: JSON.stringify({ sender: `demo-${Date.now()}`, text: "banjir darurat di Sayung Demak, jalan putus, ada lansia sakit perlu medis dan evakuasi", lat: -6.919, lon: 110.518, location_label: "Sayung, Demak" }),
        });
        showToast("Laporan demo berhasil dibuat.");
        await refresh();
      } catch (error) {
        showToast(error.message);
      }
    });

    $("#open-alert").addEventListener("click", () => $("#alert-dialog").showModal());
    document.querySelectorAll("[data-close-alert]").forEach((button) => button.addEventListener("click", () => $("#alert-dialog").close()));
    $("#alert-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.currentTarget));
      values.lat = Number(values.lat);
      values.lon = Number(values.lon);
      values.radius_km = Number(values.radius_km);
      try {
        const result = await api("/api/admin/alerts", { method: "POST", body: JSON.stringify(values) });
        $("#alert-dialog").close();
        showToast(`Peringatan dicatat untuk ${result.delivery_count} penerima.`);
      } catch (error) {
        showToast(error.message);
      }
    });
  }

  const boot = async () => {
    setLocation(fallbackLocation);
    if (responder) {
      organizations = await fetch("/api/organizations").then((response) => response.json()).catch(() => []);
      $("#organization").innerHTML = organizations.map((organization) => `<option value="${organization.id}">${escapeHtml(organization.name)}</option>`).join("") || "<option>Organisasi tidak tersedia</option>";
    }
    const params = new URLSearchParams(window.location.search);
    if (params.has("lat") && params.has("lon")) map.setView([Number(params.get("lat")), Number(params.get("lon"))], 11);
    await refresh();
    window.setInterval(() => refresh({ quiet: true }), 15000);
  };

  boot();
})();
