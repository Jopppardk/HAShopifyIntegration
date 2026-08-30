class ShopifyPackagingCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._report = null;
    this._loading = false;
    this._period = "current_quarter";
    this._customStart = "";
    this._customEnd = "";
    this._editing = null;
    this._message = "";
  }

  setConfig(config) {
    this._config = { title: "Emballageoverblik", ...config };
    if (this._hass && !this._report && !this._loading) this._load();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._config && !this._report && !this._loading) this._load();
  }

  getCardSize() {
    return 16;
  }

  static getStubConfig() {
    return { title: "Emballageoverblik" };
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  _kg(grams) {
    return new Intl.NumberFormat("da-DK", {
      minimumFractionDigits: 3,
      maximumFractionDigits: 3,
    }).format(Number(grams || 0) / 1000) + " kg";
  }

  _money(value) {
    return new Intl.NumberFormat("da-DK", {
      style: "currency",
      currency: "DKK",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(Number(value || 0));
  }

  _date(value) {
    return new Intl.DateTimeFormat("da-DK", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(new Date(value + "T12:00:00"));
  }

  _status(value) {
    return value === "yes" ? "Ja" : value === "no" ? "Nej" : "Uafklaret";
  }

  async _load() {
    this._loading = true;
    this._renderLoading();
    try {
      const request = { type: "shopify_integration/packaging/get" };
      if (this._config.config_entry_id) {
        request.config_entry_id = this._config.config_entry_id;
      }
      if (this._period === "custom" && this._customStart && this._customEnd) {
        request.start_date = this._customStart;
        request.end_date = this._customEnd;
      }
      this._report = await this._hass.callWS(request);
      this._configEntryId = this._report.config_entry_id;
      this._render();
    } catch (error) {
      this._renderError(error?.message || String(error));
    } finally {
      this._loading = false;
    }
  }

  _renderLoading() {
    this.shadowRoot.innerHTML = `
      <ha-card><div class="loading">
        <ha-circular-progress active></ha-circular-progress>
        <span>Indlæser emballagedata fra Shopify…</span>
      </div></ha-card>${this._styles()}`;
  }

  _renderError(message) {
    this.shadowRoot.innerHTML = `
      <ha-card><div class="error">
        <ha-icon icon="mdi:alert-circle"></ha-icon>
        <div><strong>Emballagedata kunne ikke indlæses</strong>
        <p>${this._escape(message)}</p></div>
      </div></ha-card>${this._styles()}`;
  }

  _periodSummary(label, grams, cost) {
    return `<div class="summary-box accent">
      <div class="summary-label">${this._escape(label)}</div>
      <div class="summary-value">${this._kg(grams)}</div>
      <div class="summary-cost">Estimeret pris: <strong>${this._money(cost)}</strong></div>
    </div>`;
  }

  _periodLabel() {
    return {
      current_quarter: "Indeværende kvartal",
      previous_quarter: "Forrige kvartal",
      year_to_date: "År til dato",
      previous_year: "Sidste kalenderår",
      custom: "Brugerdefineret periode",
    }[this._period] || "Valgt periode";
  }

  _periodSelector() {
    return `<div class="period-controls">
      <label>Vis periode
        <select class="period-select">
          <option value="current_quarter" ${this._period === "current_quarter" ? "selected" : ""}>Indeværende kvartal</option>
          <option value="previous_quarter" ${this._period === "previous_quarter" ? "selected" : ""}>Forrige kvartal</option>
          <option value="year_to_date" ${this._period === "year_to_date" ? "selected" : ""}>År til dato</option>
          <option value="previous_year" ${this._period === "previous_year" ? "selected" : ""}>Sidste kalenderår</option>
          <option value="custom" ${this._period === "custom" ? "selected" : ""}>Brugerdefineret…</option>
        </select>
      </label>
      ${this._period === "custom" ? `<form class="custom-period">
        <label>Fra <input type="date" name="start_date" value="${this._escape(this._customStart)}" required></label>
        <label>Til <input type="date" name="end_date" value="${this._escape(this._customEnd)}" required></label>
        <button type="submit" class="secondary">Vis</button>
      </form>` : ""}
    </div>`;
  }

  _productRows(period) {
    if (!period.products.length) {
      return '<div class="empty">Ingen produktrelateret emballage i perioden.</div>';
    }
    return period.products.map((product) => {
      const orders = product.orders.map((order) => `
        <tr>
          <td>${this._escape(order.order_name)}</td>
          <td>${this._date(order.date)}</td>
          <td class="number">${order.quantity}</td>
          <td class="number">${order.weight_grams === null ? "Mangler" : order.weight_grams + " g"}</td>
          <td class="number">${this._kg(order.grams)}</td>
          <td><span class="status ${order.reportable}">${this._status(order.reportable)}</span></td>
        </tr>`).join("");
      return `
        <details>
          <summary>
            <span><strong>${this._escape(product.product)}</strong>
              <small>${product.quantity} stk.</small></span>
            <span class="product-values">
              <span>${this._kg(product.grams)}</span>
              <span class="reportable">${this._kg(product.reportable_grams)} indberetningspligtigt</span>
            </span>
          </summary>
          <div class="table-wrap">
            <table>
              <thead><tr>
                <th>Ordre</th><th>Dato</th>
                <th class="number">Antal</th><th class="number">Pr. stk.</th>
                <th class="number">Samlet</th><th>Indberetning</th>
              </tr></thead>
              <tbody>${orders}</tbody>
            </table>
          </div>
        </details>`;
    }).join("");
  }

  _manualRows(entries = this._report.manual_entries) {
    if (!entries.length) {
      return '<tr><td colspan="8" class="empty">Ingen manuelle registreringer endnu.</td></tr>';
    }
    return entries.map((entry) => `
      <tr>
        <td>${this._date(entry.date)}</td>
        <td>${this._escape(entry.description)}</td>
        <td>${this._escape(entry.supplier || "—")}</td>
        <td>${this._escape(entry.supplier_country || "—")}</td>
        <td>${this._escape(entry.supplier_cvr || "—")}</td>
        <td class="number">${this._kg(entry.weight_grams)}</td>
        <td><span class="status ${entry.reportable}">${this._status(entry.reportable)}</span></td>
        <td class="actions">
          <button class="icon edit" data-id="${this._escape(entry.id)}" title="Rediger">
            <ha-icon icon="mdi:pencil"></ha-icon>
          </button>
          <button class="icon delete" data-id="${this._escape(entry.id)}" title="Slet">
            <ha-icon icon="mdi:delete"></ha-icon>
          </button>
        </td>
      </tr>`).join("");
  }

  _manualForm() {
    const entry = this._editing || {};
    const today = new Date().toLocaleDateString("sv-SE");
    return `
      <form class="manual-form">
        <input type="hidden" name="entry_id" value="${this._escape(entry.id || "")}">
        <label>Dato<input required type="date" name="date" value="${this._escape(entry.date || today)}"></label>
        <label class="wide">Beskrivelse<input required maxlength="200" name="description"
          placeholder="Fx importeret transportkasse og plast" value="${this._escape(entry.description || "")}"></label>
        <label>Leverandør<input maxlength="200" name="supplier" value="${this._escape(entry.supplier || "")}"></label>
        <label>Leverandørland<input maxlength="100" name="supplier_country"
          placeholder="Fx CN eller DK" value="${this._escape(entry.supplier_country || "")}"></label>
        <label>Leverandør-CVR<input maxlength="50" name="supplier_cvr" value="${this._escape(entry.supplier_cvr || "")}"></label>
        <label>Samlet vægt i gram<input required min="0" step="1" type="number"
          name="weight_grams" value="${this._escape(entry.weight_grams ?? "")}"></label>
        <label>Indberetningspligtig<select name="reportable">
          <option value="unknown" ${!entry.reportable || entry.reportable === "unknown" ? "selected" : ""}>Uafklaret</option>
          <option value="yes" ${entry.reportable === "yes" ? "selected" : ""}>Ja</option>
          <option value="no" ${entry.reportable === "no" ? "selected" : ""}>Nej</option>
        </select></label>
        <div class="form-actions">
          <button type="button" class="secondary cancel">${entry.id ? "Annuller" : "Nulstil"}</button>
          <button type="submit" class="primary">${entry.id ? "Gem ændringer" : "Tilføj registrering"}</button>
        </div>
      </form>`;
  }

  _render() {
    const selected = this._report.periods[this._period] || this._report.periods.current_quarter;
    const pricePerKg = Number(this._report.price_per_kg || 0);
    const selectedCost = selected.reportable_grams / 1000 * pricePerKg;
    const warnings = [];
    if (selected.unconfigured_product_lines) {
      warnings.push(`${selected.unconfigured_product_lines} fulfillmentlinjer mangler emballagevægt`);
    }
    if (selected.unknown_reportability_grams) {
      warnings.push(`${this._kg(selected.unknown_reportability_grams)} har uafklaret indberetningsstatus`);
    }

    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="header">
          <div><div class="title">${this._escape(this._config.title)}</div>
          <div class="subtitle">Q${this._report.quarter_number} · ${this._report.year}</div></div>
          <button class="secondary reload">Genindlæs</button>
        </div>

        ${this._message ? `<div class="message">${this._escape(this._message)}</div>` : ""}

        <section>
          <div class="summary-heading">
            <h2>Samlet emballage</h2>
            ${this._periodSelector()}
          </div>
          <div class="summary-grid">
            ${this._periodSummary(this._periodLabel(), selected.reportable_grams, selectedCost)}
          </div>
          <form class="price-form">
            <label>Estimeret pris pr. kg
              <span><input name="price_per_kg" type="number" min="0" max="1000" step="0.01"
                value="${pricePerKg.toFixed(2)}" required> kr./kg</span>
            </label>
            <button type="submit" class="secondary">Gem sats</button>
            <small>Standard: 3,79 kr./kg for samlet husholdningsemballage i 2026. Ekskl. moms og faste gebyrer.</small>
          </form>
        </section>

        <section>
          <div class="section-heading">
            <div><h2>Emballage fra produktsalg</h2>
              <p>Baseret på succesfulde Shopify-fulfillments.</p></div>
            <strong class="selected-period">${this._periodLabel()}</strong>
          </div>
          <div class="product-summary">
            <span>Samlet: <strong>${this._kg(selected.product_grams)}</strong></span>
            <span>Indberetningspligtigt: <strong>${this._kg(selected.product_reportable_grams)}</strong></span>
          </div>
          ${warnings.length ? `<div class="warning">${warnings.map(this._escape).join(" · ")}</div>` : ""}
          <div class="products">${this._productRows(selected)}</div>
        </section>

        <section>
          <h2>Øvrig emballage</h2>
          <p>Manuelle poster gemmes permanent i Home Assistant. Vægten er postens samlede gram.</p>
          ${this._manualForm()}
          <div class="table-wrap manual-table"><table>
            <thead><tr><th>Dato</th><th>Beskrivelse</th><th>Leverandør</th>
              <th>Land</th><th>CVR</th><th class="number">Vægt</th>
              <th>Indberetning</th><th></th></tr></thead>
            <tbody>${this._manualRows(selected.manual_entries)}</tbody>
          </table></div>
        </section>
      </ha-card>${this._styles()}`;

    this.shadowRoot.querySelector(".reload").addEventListener("click", () => this._load());
    this.shadowRoot.querySelector(".period-select").addEventListener("change", (event) => {
      this._period = event.currentTarget.value;
      if (this._period === "custom") {
        const today = new Date();
        this._customEnd = today.toISOString().slice(0, 10);
        this._customStart = `${today.getFullYear()}-01-01`;
        this._load();
        return;
      }
      this._render();
    });
    const customPeriod = this.shadowRoot.querySelector(".custom-period");
    if (customPeriod) {
      customPeriod.addEventListener("submit", (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        this._customStart = form.get("start_date");
        this._customEnd = form.get("end_date");
        this._load();
      });
    }
    this.shadowRoot.querySelector(".price-form").addEventListener("submit", (event) => this._savePrice(event));
    this.shadowRoot.querySelector(".manual-form").addEventListener("submit", (event) => this._saveManual(event));
    this.shadowRoot.querySelector(".cancel").addEventListener("click", () => {
      this._editing = null;
      this._render();
    });
    this.shadowRoot.querySelectorAll(".edit").forEach((button) => {
      button.addEventListener("click", () => {
        this._editing = this._report.manual_entries.find((entry) => entry.id === button.dataset.id);
        this._render();
        this.shadowRoot.querySelector(".manual-form").scrollIntoView({ behavior: "smooth", block: "center" });
      });
    });
    this.shadowRoot.querySelectorAll(".delete").forEach((button) => {
      button.addEventListener("click", () => this._deleteManual(button.dataset.id));
    });
  }

  async _savePrice(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await this._hass.callWS({
        type: "shopify_integration/packaging/price/set",
        config_entry_id: this._configEntryId,
        price_per_kg: Number(form.get("price_per_kg")),
      });
      this._message = "Den estimerede kg-sats er gemt.";
      await this._load();
    } catch (error) {
      this._message = error?.message || String(error);
      this._render();
    }
  }

  async _saveManual(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const request = {
      type: "shopify_integration/packaging/manual/upsert",
      config_entry_id: this._configEntryId,
      date: form.get("date"),
      description: form.get("description"),
      supplier: form.get("supplier"),
      supplier_country: form.get("supplier_country"),
      supplier_cvr: form.get("supplier_cvr"),
      weight_grams: Number(form.get("weight_grams")),
      reportable: form.get("reportable"),
    };
    if (form.get("entry_id")) request.entry_id = form.get("entry_id");
    try {
      await this._hass.callWS(request);
      this._editing = null;
      this._message = "Den manuelle emballageregistrering er gemt.";
      await this._load();
    } catch (error) {
      this._message = error?.message || String(error);
      this._render();
    }
  }

  async _deleteManual(entryId) {
    const entry = this._report.manual_entries.find((item) => item.id === entryId);
    if (!entry || !window.confirm(`Slet registreringen "${entry.description}"?`)) return;
    try {
      await this._hass.callWS({
        type: "shopify_integration/packaging/manual/delete",
        config_entry_id: this._configEntryId,
        entry_id: entryId,
      });
      this._message = "Registreringen er slettet.";
      await this._load();
    } catch (error) {
      this._message = error?.message || String(error);
      this._render();
    }
  }

  _styles() {
    return `<style>
      :host { display: block; }
      ha-card { overflow: hidden; }
      .header, .section-heading, .summary-heading { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
      .header { padding: 20px; border-bottom: 1px solid var(--divider-color); }
      .title { font-size: 24px; font-weight: 650; }
      .subtitle, p, small { color: var(--secondary-text-color); }
      p { margin: 4px 0 14px; }
      section { padding: 20px; border-bottom: 1px solid var(--divider-color); }
      section:last-child { border-bottom: 0; }
      h2 { margin: 0 0 12px; font-size: 19px; }
      .section-heading h2 { margin-bottom: 3px; }
      .summary-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; max-width: 620px; }
      .period-controls, .custom-period { display: flex; flex-wrap: wrap; align-items: end; gap: 10px; }
      .period-controls label, .custom-period label { display: flex; flex-direction: column; gap: 4px; color: var(--secondary-text-color); font-size: 12px; }
      .period-select { min-width: 210px; }
      .selected-period { color: var(--secondary-text-color); }
      .summary-box { padding: 16px; border-radius: 12px; background: var(--secondary-background-color); }
      .summary-box.accent { background: color-mix(in srgb, var(--primary-color) 16%, var(--card-background-color)); }
      .summary-cost { margin-top: 8px; color: var(--secondary-text-color); font-size: 14px; }
      .summary-cost strong { color: var(--primary-text-color); font-size: 17px; }
      .price-form { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; margin-top: 14px; }
      .price-form label { display: flex; flex-direction: column; gap: 5px; color: var(--secondary-text-color); font-size: 12px; }
      .price-form input { width: 110px; }
      .price-form small { flex-basis: 100%; }
      .summary-label { min-height: 34px; color: var(--secondary-text-color); font-size: 13px; }
      .summary-value { margin-top: 6px; font-size: 23px; font-weight: 650; }
      button { min-height: 38px; padding: 0 14px; border: 0; border-radius: 9px; font: inherit; font-weight: 600; cursor: pointer; }
      button.primary { color: var(--text-primary-color); background: var(--primary-color); }
      button.secondary, .tabs button { color: var(--primary-text-color); background: var(--secondary-background-color); }
      .tabs { display: flex; gap: 4px; padding: 4px; border-radius: 11px; background: var(--secondary-background-color); }
      .tabs button.active { color: var(--text-primary-color); background: var(--primary-color); }
      .product-summary { display: flex; flex-wrap: wrap; gap: 24px; margin: 12px 0; }
      .warning, .message { margin: 10px 0 14px; padding: 11px 13px; border-radius: 9px; background: color-mix(in srgb, var(--warning-color, #ffa000) 18%, transparent); }
      .message { margin: 14px 20px 0; background: color-mix(in srgb, var(--primary-color) 14%, transparent); }
      details { border-top: 1px solid var(--divider-color); }
      details:last-child { border-bottom: 1px solid var(--divider-color); }
      summary { display: flex; justify-content: space-between; gap: 16px; padding: 13px 8px; cursor: pointer; }
      summary small { margin-left: 8px; }
      .product-values { display: flex; gap: 18px; text-align: right; }
      .product-values .reportable { color: var(--primary-color); }
      .table-wrap { overflow-x: auto; }
      table { width: 100%; border-collapse: collapse; min-width: 760px; font-size: 13px; }
      th, td { padding: 10px 8px; text-align: left; border-bottom: 1px solid var(--divider-color); }
      th { color: var(--secondary-text-color); }
      .number { text-align: right; white-space: nowrap; }
      .status { display: inline-block; padding: 3px 7px; border-radius: 99px; background: var(--secondary-background-color); }
      .status.yes { color: var(--error-color); }
      .status.no { color: var(--success-color, #43a047); }
      .status.unknown { color: var(--warning-color, #ffa000); }
      .manual-form { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 16px 0 20px; padding: 16px; border-radius: 12px; background: var(--secondary-background-color); }
      .manual-form label { display: flex; flex-direction: column; gap: 5px; color: var(--secondary-text-color); font-size: 12px; }
      .manual-form label.wide { grid-column: span 2; }
      input, select { box-sizing: border-box; width: 100%; min-height: 40px; padding: 8px 10px; border: 1px solid var(--divider-color); border-radius: 8px; color: var(--primary-text-color); background: var(--card-background-color); font: inherit; }
      .form-actions { grid-column: 1 / -1; display: flex; justify-content: flex-end; gap: 8px; }
      .actions { white-space: nowrap; }
      button.icon { min-width: 34px; padding: 0 6px; color: var(--primary-text-color); background: transparent; }
      button.delete { color: var(--error-color); }
      .empty { padding: 20px 8px; color: var(--secondary-text-color); text-align: center; }
      .loading, .error { display: flex; gap: 14px; align-items: center; padding: 28px; }
      .error ha-icon { color: var(--error-color); }
      @media (max-width: 900px) {
        .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .manual-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
      @media (max-width: 600px) {
        .header, .section-heading, .summary-heading, summary { align-items: stretch; flex-direction: column; }
        .summary-grid, .manual-form { grid-template-columns: 1fr; }
        .manual-form label.wide { grid-column: auto; }
        .product-values { justify-content: space-between; text-align: left; }
        .tabs button { flex: 1; }
      }
    </style>`;
  }
}

customElements.define("shopify-packaging-card", ShopifyPackagingCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "shopify-packaging-card",
  name: "Shopify Packaging Dashboard",
  description: "Packaging consumption and Danish reporting overview",
  preview: false,
});
