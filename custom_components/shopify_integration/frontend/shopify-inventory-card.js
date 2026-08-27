class ShopifyInventoryCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._items = [];
    this._draft = new Map();
    this._loading = false;
    this._loaded = false;
    this._message = "";
    this._messageTone = "info";
  }

  setConfig(config) {
    this._config = {
      title: "Lageroptælling",
      ...config,
    };
    if (this._hass && !this._loaded) this._load();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._config && !this._loaded && !this._loading) this._load();
  }

  getCardSize() {
    return 12;
  }

  static getStubConfig() {
    return { title: "Lageroptælling" };
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  async _load(preservedDraft = new Map()) {
    this._loading = true;
    this._renderLoading();
    try {
      const request = { type: "shopify_integration/inventory/get" };
      if (this._config.config_entry_id) {
        request.config_entry_id = this._config.config_entry_id;
      }
      const result = await this._hass.callWS(request);
      this._configEntryId = result.config_entry_id;
      this._location = result.location;
      this._items = result.items;
      this._draft = new Map();
      for (const item of this._items) {
        if (preservedDraft.has(item.inventory_item_id)) {
          const quantity = preservedDraft.get(item.inventory_item_id);
          if (quantity !== item.on_hand) {
            this._draft.set(item.inventory_item_id, quantity);
          }
        }
      }
      this._loaded = true;
      this._message = this._message || `${this._items.length} varianter indlæst`;
      this._messageTone = this._messageTone || "info";
      this._render();
    } catch (error) {
      this._loaded = false;
      this._renderError(error?.message || String(error));
    } finally {
      this._loading = false;
    }
  }

  _renderLoading() {
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="loading">
          <ha-circular-progress active></ha-circular-progress>
          <span>Indlæser lagerliste fra Shopify…</span>
        </div>
      </ha-card>
      ${this._styles()}
    `;
  }

  _renderError(message) {
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="error">
          <ha-icon icon="mdi:alert-circle"></ha-icon>
          <div>
            <strong>Lagerlisten kunne ikke indlæses</strong>
            <p>${this._escape(message)}</p>
          </div>
        </div>
      </ha-card>
      ${this._styles()}
    `;
  }

  _styles() {
    return `
      <style>
        :host { display: block; }
        ha-card { overflow: hidden; }
        .header {
          display: flex;
          gap: 16px;
          align-items: center;
          justify-content: space-between;
          padding: 18px 20px 12px;
        }
        .title { font-size: 22px; font-weight: 600; }
        .subtitle {
          color: var(--secondary-text-color);
          font-size: 13px;
          margin-top: 3px;
        }
        .toolbar {
          display: grid;
          grid-template-columns: minmax(180px, 1fr) auto auto;
          gap: 10px;
          padding: 0 20px 14px;
        }
        .search {
          box-sizing: border-box;
          width: 100%;
          min-height: 42px;
          padding: 0 12px;
          border: 1px solid var(--divider-color);
          border-radius: 10px;
          color: var(--primary-text-color);
          background: var(--card-background-color);
          font: inherit;
        }
        button {
          min-height: 42px;
          padding: 0 16px;
          border: 0;
          border-radius: 10px;
          font: inherit;
          font-weight: 600;
          cursor: pointer;
        }
        button.primary {
          color: var(--text-primary-color);
          background: var(--primary-color);
        }
        button.secondary {
          color: var(--primary-text-color);
          background: var(--secondary-background-color);
        }
        button:disabled { opacity: .45; cursor: default; }
        .message {
          margin: 0 20px 12px;
          padding: 10px 12px;
          border-radius: 9px;
          background: color-mix(in srgb, var(--primary-color) 12%, transparent);
        }
        .message.success {
          background: color-mix(in srgb, var(--success-color, #43a047) 16%, transparent);
        }
        .message.warning {
          background: color-mix(in srgb, var(--warning-color, #ffa000) 18%, transparent);
        }
        .table-wrap {
          max-height: var(--shopify-inventory-table-height, 68vh);
          overflow: auto;
          border-top: 1px solid var(--divider-color);
          border-bottom: 1px solid var(--divider-color);
        }
        table {
          width: 100%;
          border-collapse: separate;
          border-spacing: 0;
          font-size: 14px;
        }
        th {
          position: sticky;
          top: 0;
          z-index: 2;
          text-align: left;
          padding: 11px 12px;
          color: var(--secondary-text-color);
          background: var(--card-background-color);
          border-bottom: 1px solid var(--divider-color);
        }
        th.number, td.number { text-align: right; }
        td {
          padding: 9px 12px;
          border-bottom: 1px solid var(--divider-color);
          vertical-align: middle;
        }
        tr.changed td {
          background: color-mix(in srgb, var(--primary-color) 9%, transparent);
        }
        tr.hidden { display: none; }
        .product { font-weight: 500; }
        .variant, .muted {
          color: var(--secondary-text-color);
          font-size: 12px;
          margin-top: 2px;
        }
        .quantity {
          box-sizing: border-box;
          width: 88px;
          padding: 8px 9px;
          text-align: right;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          color: var(--primary-text-color);
          background: var(--card-background-color);
          font: inherit;
        }
        .quantity:focus {
          outline: 2px solid var(--primary-color);
          outline-offset: 1px;
        }
        .difference.positive { color: var(--success-color, #43a047); }
        .difference.negative { color: var(--error-color, #db4437); }
        .footer {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          align-items: center;
          padding: 14px 20px 18px;
        }
        .summary { color: var(--secondary-text-color); }
        .loading, .error {
          display: flex;
          gap: 14px;
          align-items: center;
          padding: 28px;
        }
        .error ha-icon { color: var(--error-color); }
        @media (max-width: 700px) {
          .header, .footer { align-items: stretch; flex-direction: column; }
          .toolbar { grid-template-columns: 1fr 1fr; }
          .search { grid-column: 1 / -1; }
          th:nth-child(3), td:nth-child(3) { display: none; }
          td, th { padding-left: 8px; padding-right: 8px; }
          .quantity { width: 76px; }
        }
      </style>
    `;
  }

  _render() {
    const rows = this._items.map((item) => {
      const counted = this._draft.has(item.inventory_item_id)
        ? this._draft.get(item.inventory_item_id)
        : item.on_hand;
      const difference = counted - item.on_hand;
      const variant = item.variant === "Default Title" ? "" : item.variant;
      const searchable = [
        item.product, item.variant, item.sku, item.barcode, item.display_name
      ].join(" ").toLocaleLowerCase();
      return `
        <tr data-id="${this._escape(item.inventory_item_id)}"
            data-search="${this._escape(searchable)}"
            class="${difference !== 0 ? "changed" : ""}">
          <td>
            <div class="product">${this._escape(item.product)}</div>
            ${variant ? `<div class="variant">${this._escape(variant)}</div>` : ""}
          </td>
          <td>
            <div>${this._escape(item.sku || "—")}</div>
            ${item.barcode ? `<div class="muted">${this._escape(item.barcode)}</div>` : ""}
          </td>
          <td class="number">${item.on_hand}</td>
          <td class="number">
            <input class="quantity" type="number" min="0" step="1"
              inputmode="numeric" value="${counted}"
              aria-label="Optalt antal for ${this._escape(item.display_name)}">
          </td>
          <td class="number difference ${difference > 0 ? "positive" : difference < 0 ? "negative" : ""}">
            ${difference > 0 ? "+" : ""}${difference}
          </td>
        </tr>
      `;
    }).join("");

    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="header">
          <div>
            <div class="title">${this._escape(this._config.title)}</div>
            <div class="subtitle">
              ${this._escape(this._location?.name || "")} · fysisk lager (on hand)
            </div>
          </div>
        </div>

        <div class="toolbar">
          <input class="search" type="search"
            placeholder="Filtrér efter produkt, variant, SKU eller stregkode">
          <button class="secondary reset" type="button">Nulstil ændringer</button>
          <button class="secondary reload" type="button">Genindlæs</button>
        </div>

        ${this._message ? `<div class="message ${this._messageTone}">${this._escape(this._message)}</div>` : ""}

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Produkt og variant</th>
                <th>SKU / stregkode</th>
                <th class="number">Shopify</th>
                <th class="number">Optalt</th>
                <th class="number">Difference</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>

        <div class="footer">
          <div class="summary"></div>
          <button class="primary update" type="button">
            Gennemgå og opdater lager
          </button>
        </div>
      </ha-card>
      ${this._styles()}
    `;

    this.shadowRoot.querySelectorAll(".quantity").forEach((input) => {
      input.addEventListener("input", (event) => this._quantityChanged(event));
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          const inputs = [...this.shadowRoot.querySelectorAll(".quantity")];
          const index = inputs.indexOf(event.currentTarget);
          inputs[index + 1]?.focus();
          inputs[index + 1]?.select();
        }
      });
    });
    this.shadowRoot.querySelector(".search").addEventListener(
      "input", (event) => this._filter(event.target.value)
    );
    this.shadowRoot.querySelector(".reset").addEventListener(
      "click", () => this._reset()
    );
    this.shadowRoot.querySelector(".reload").addEventListener(
      "click", () => {
        this._loaded = false;
        this._message = "";
        this._load();
      }
    );
    this.shadowRoot.querySelector(".update").addEventListener(
      "click", () => this._reviewAndUpdate()
    );
    this._updateSummary();
  }

  _quantityChanged(event) {
    const row = event.currentTarget.closest("tr");
    const item = this._items.find(
      (candidate) => candidate.inventory_item_id === row.dataset.id
    );
    const raw = event.currentTarget.value;
    const quantity = raw === "" ? item.on_hand : Number(raw);
    if (!Number.isInteger(quantity) || quantity < 0) return;

    if (quantity === item.on_hand) {
      this._draft.delete(item.inventory_item_id);
    } else {
      this._draft.set(item.inventory_item_id, quantity);
    }
    const difference = quantity - item.on_hand;
    row.classList.toggle("changed", difference !== 0);
    const differenceCell = row.querySelector(".difference");
    differenceCell.textContent = `${difference > 0 ? "+" : ""}${difference}`;
    differenceCell.classList.toggle("positive", difference > 0);
    differenceCell.classList.toggle("negative", difference < 0);
    this._updateSummary();
  }

  _updateSummary() {
    const changes = [...this._draft.entries()].map(([id, quantity]) => {
      const item = this._items.find(
        (candidate) => candidate.inventory_item_id === id
      );
      return { item, quantity, difference: quantity - item.on_hand };
    });
    const increases = changes.filter((change) => change.difference > 0).length;
    const reductions = changes.filter((change) => change.difference < 0).length;
    this.shadowRoot.querySelector(".summary").textContent =
      changes.length === 0
        ? "Ingen lagerændringer"
        : `${changes.length} ændringer · ${increases} forhøjes · ${reductions} reduceres`;
    this.shadowRoot.querySelector(".update").disabled = changes.length === 0;
    this.shadowRoot.querySelector(".reset").disabled = changes.length === 0;
  }

  _filter(value) {
    const filter = value.trim().toLocaleLowerCase();
    this.shadowRoot.querySelectorAll("tbody tr").forEach((row) => {
      row.classList.toggle("hidden", filter && !row.dataset.search.includes(filter));
    });
  }

  _reset() {
    if (this._draft.size && !window.confirm("Nulstil alle indtastede lagerændringer?")) {
      return;
    }
    this._draft.clear();
    this._message = "";
    this._render();
  }

  async _reviewAndUpdate() {
    const updates = [...this._draft.entries()].map(([id, quantity]) => {
      const item = this._items.find(
        (candidate) => candidate.inventory_item_id === id
      );
      return {
        inventory_item_id: id,
        expected_quantity: item.on_hand,
        quantity,
        difference: quantity - item.on_hand,
      };
    });
    if (!updates.length) return;

    const increases = updates.filter((update) => update.difference > 0).length;
    const reductions = updates.filter((update) => update.difference < 0).length;
    const setToZero = updates.filter((update) => update.quantity === 0).length;
    const review = [
      "Gennemgå og opdater lager",
      "",
      `Du er ved at opdatere ${updates.length} varianter i Shopify:`,
      `${reductions} reduceres`,
      `${increases} forhøjes`,
      `${setToZero} sættes til 0`,
      "",
      "Dinero og bogføring påvirkes ikke.",
      "",
      "Vil du opdatere lageret?"
    ].join("\n");
    if (!window.confirm(review)) return;

    const button = this.shadowRoot.querySelector(".update");
    button.disabled = true;
    button.textContent = "Opdaterer lager…";
    try {
      const result = await this._hass.callWS({
        type: "shopify_integration/inventory/update",
        config_entry_id: this._configEntryId,
        updates: updates.map(({ difference, ...update }) => update),
      });
      const preserved = new Map();
      for (const conflict of result.conflicts) {
        const original = updates.find(
          (update) => update.inventory_item_id === conflict.inventory_item_id
        );
        if (original) preserved.set(original.inventory_item_id, original.quantity);
      }
      this._message = result.conflict_count
        ? `${result.updated_count} varianter blev opdateret. ${result.conflict_count} kræver ny gennemgang, fordi Shopify-lageret ændrede sig.`
        : `Lageret er opdateret: ${result.updated_count} varianter blev ændret.`;
      this._messageTone = result.conflict_count ? "warning" : "success";
      this._loaded = false;
      await this._load(preserved);
    } catch (error) {
      this._message = error?.message || String(error);
      this._messageTone = "warning";
      this._render();
    }
  }
}

customElements.define("shopify-inventory-card", ShopifyInventoryCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "shopify-inventory-card",
  name: "Shopify Inventory Count",
  description: "Bulk inventory counting for Shopify Integration",
  preview: false,
});
