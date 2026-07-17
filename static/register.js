(() => {
  const form = document.querySelector("#application-form");
  const result = document.querySelector("#submission-result");

  const setKind = () => {
    const kind = form.elements.applicant_kind.value;
    document.querySelector("#organization-documents").hidden = kind !== "organization";
    document.querySelector("#individual-documents").hidden = kind !== "individual";
    form.elements.legal.required = kind === "organization";
    form.elements.mandate.required = kind === "organization";
    form.elements.identity.required = kind === "individual";
  };

  form.querySelectorAll('input[name="applicant_kind"]').forEach((input) => input.addEventListener("change", setKind));
  setKind();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form));
    const organization = values.applicant_kind === "organization";
    const documentLinks = organization
      ? { legal: values.legal, mandate: values.mandate, portfolio: values.portfolio_org }
      : { identity: values.identity, certificate: values.certificate, portfolio: values.portfolio_individual };
    const payload = {
      applicant_kind: values.applicant_kind,
      name: values.name,
      type: organization ? values.type : "individual_volunteer",
      email: values.email,
      phone: values.phone,
      address: values.address,
      contact_name: values.contact_name,
      contact_role: values.contact_role,
      logo_url: values.logo_url,
      website: values.website,
      operational_areas: values.operational_areas.split(",").map((area) => area.trim()).filter(Boolean),
      document_links: Object.fromEntries(Object.entries(documentLinks).filter(([, value]) => value?.trim())),
    };
    try {
      const response = await fetch("/api/organizations/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Pendaftaran gagal");
      result.innerHTML = `<strong>Pendaftaran #${data.id} sudah diterima.</strong><br />Status saat ini: menunggu verifikasi admin. Kami akan menghubungi ${window.PetaNih.escapeHtml(data.email)} setelah pemeriksaan.`;
      result.classList.add("visible");
      form.querySelector('button[type="submit"]').disabled = true;
      result.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (error) {
      window.PetaNih.showToast(error.message, 5000);
    }
  });
})();
