function _esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Editor ────────────────────────────────────────────────────────────────────

class HaikuboxBirdListCardEditor extends HTMLElement {
  // No shadow DOM — light DOM avoids isolation issues with ha-entity-picker

  setConfig(config) {
    this._config = config;
    if (!this._built) {
      this._built = true;
      this._init();
    } else {
      if (this._picker)     this._picker.value     = config.entity ?? "";
      if (this._titleField) this._titleField.value = config.title ?? "";
      if (this._topField)   this._topField.value   = config.top ?? 10;
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._built = true;
      this._init();
    } else if (this._picker) {
      this._picker.hass = hass;
    }
  }

  _fire(update) {
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: { ...this._config, ...update } },
      bubbles: true,
      composed: true,
    }));
  }

  async _init() {
    try {
      if (window.loadCardHelpers) await window.loadCardHelpers();
    } catch (_) { /* ignore */ }

    const form = document.createElement("div");
    form.style.cssText = "display:flex;flex-direction:column;gap:4px;padding:0 16px 16px";

    let entityField;
    if (customElements.get("ha-entity-picker")) {
      entityField = document.createElement("ha-entity-picker");
      entityField.label = "Entity";
      entityField.setAttribute("allow-custom-entity", "");
      entityField.includeDomains = ["sensor"];
      if (this._hass) entityField.hass = this._hass;
      entityField.value = this._config?.entity ?? "";
      entityField.addEventListener("value-changed", (e) => this._fire({ entity: e.detail.value }));
    } else if (customElements.get("ha-selector")) {
      entityField = document.createElement("ha-selector");
      entityField.label = "Entity";
      entityField.selector = { entity: { domain: ["sensor"] } };
      if (this._hass) entityField.hass = this._hass;
      entityField.value = this._config?.entity ?? "";
      entityField.addEventListener("value-changed", (e) => this._fire({ entity: e.detail.value }));
    } else {
      entityField = document.createElement("ha-textfield");
      entityField.label = "Entity ID";
      entityField.value = this._config?.entity ?? "";
      entityField.addEventListener("change", (e) => this._fire({ entity: e.target.value }));
    }
    entityField.style.cssText = "display:block;width:100%";
    this._picker = entityField;

    const titleField = document.createElement("ha-textfield");
    titleField.label = "Title (optional)";
    titleField.style.cssText = "display:block;width:100%";
    titleField.value = this._config?.title ?? "";
    titleField.addEventListener("change", (e) => this._fire({ title: e.target.value }));
    this._titleField = titleField;

    const topField = document.createElement("ha-textfield");
    topField.label = "Max items";
    topField.type = "number";
    topField.setAttribute("min", "1");
    topField.style.cssText = "display:block;width:100%";
    topField.value = this._config?.top ?? 10;
    topField.addEventListener("change", (e) => {
      const v = parseInt(e.target.value, 10);
      this._fire({ top: isNaN(v) || v < 1 ? 10 : v });
    });
    this._topField = topField;

    form.append(entityField, titleField, topField);
    this.appendChild(form);
  }
}

customElements.define("haikubox-bird-list-card-editor", HaikuboxBirdListCardEditor);

// ── Card ──────────────────────────────────────────────────────────────────────

class HaikuboxBirdListCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  static getConfigElement() {
    return document.createElement("haikubox-bird-list-card-editor");
  }

  static getStubConfig() {
    return { entity: "", title: "", top: 10 };
  }

  setConfig(config) {
    if (config.entity === undefined) throw new Error("'entity' is required");
    this._config = { top: 10, ...config };
  }

  set hass(hass) {
    this._hass = hass;
    const stateObj = hass?.states[this._config?.entity];
    // Gate on last_updated, not last_changed: this entity's state is an
    // item count that rarely changes, while the ranked `detections`
    // attribute re-orders frequently. last_changed only moves when
    // .state changes, so it would freeze on attribute-only updates.
    // Always render at least once, even when the entity is missing
    // (lastUpdated undefined): otherwise a misconfigured card would
    // short-circuit forever and stay permanently blank instead of
    // showing its empty state.
    const lastUpdated = stateObj?.last_updated;
    if (this._rendered && lastUpdated === this._lastUpdated) return;
    this._lastUpdated = lastUpdated;
    this._rendered = true;
    this._render();
  }

  _rank(item, index) {
    // Every sensor stamps `rank` per its own criterion; index is a
    // defensive fallback only.
    return `#${item.rank ?? index + 1}`;
  }

  _relativeTime(isoString) {
    if (!isoString) return null;
    // Clamp: a future timestamp (clock skew) must not show "-3s ago".
    const diff = Math.max(0, Math.floor((Date.now() - new Date(isoString)) / 1000));
    if (diff < 60)    return `${diff}s ago`;
    if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  _render() {
    const stateObj = this._hass?.states[this._config.entity];
    const attrs = stateObj?.attributes ?? {};
    const items = (attrs.detections ?? []).slice(0, this._config.top);
    this._items = items;  // referenced by the row toggle handler
    // Fall back to the entity's friendly name when no title is set.
    // The stub config and editor write title:"" (not nullish), so a
    // plain `??` chain never reached the fallback for UI-created cards.
    const configured = this._config.title;
    const title = (configured && configured.trim())
      ? configured
      : (attrs.friendly_name ?? "");

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; height: 100%; }
        ha-card {
          overflow: hidden;
          height: 100%;
          padding: 0;
        }
        .layout {
          display: flex;
          flex-direction: column;
          height: 100%;
          padding-bottom: 4px;
        }

        .card-header {
          padding: 14px 16px 10px;
          font-size: 1.15em;
          font-weight: 600;
          text-align: center;
          color: var(--primary-text-color);
          border-bottom: 1px solid var(--divider-color);
          flex-shrink: 0;
        }

        .list {
          flex: 1;
          overflow-y: auto;
          min-height: 0;
        }
        .list::-webkit-scrollbar { width: 4px; }
        .list::-webkit-scrollbar-track { background: transparent; }
        .list::-webkit-scrollbar-thumb {
          background: var(--scrollbar-thumb-color, var(--divider-color));
          border-radius: 2px;
        }

        .row {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 6px 16px;
          border-bottom: 1px solid var(--divider-color);
          cursor: pointer;
          user-select: none;
        }
        .row:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: -2px;
        }

        .thumb {
          width: 40px;
          height: 40px;
          border-radius: 50%;
          object-fit: cover;
          flex-shrink: 0;
          background: var(--secondary-background-color);
        }
        .thumb-placeholder {
          width: 40px;
          height: 40px;
          border-radius: 50%;
          flex-shrink: 0;
          background: var(--secondary-background-color);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 1.1em;
        }

        .rank {
          width: 24px;
          font-size: 0.75em;
          font-weight: 700;
          color: var(--secondary-text-color);
          text-align: right;
          flex-shrink: 0;
        }

        .info { flex: 1; min-width: 0; }
        .name {
          font-size: 0.9em;
          font-weight: 500;
          color: var(--primary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .sub {
          font-size: 0.78em;
          font-style: italic;
          color: var(--secondary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        /* Expansion panel */
        .expansion {
          display: grid;
          grid-template-rows: 0fr;
          transition: grid-template-rows 220ms ease;
          border-bottom: 1px solid var(--divider-color);
        }
        .expansion.is-open {
          grid-template-rows: 1fr;
        }
        .expansion-inner {
          overflow: hidden;
        }
        .expansion-body {
          display: flex;
          gap: 16px;
          align-items: center;
          padding: 12px 16px 14px;
        }
        .expansion-photo {
          width: 144px;
          height: 144px;
          border-radius: var(--ha-card-border-radius, 4px);
          object-fit: cover;
          flex-shrink: 0;
          background: var(--secondary-background-color);
        }
        .expansion-photo-placeholder {
          width: 144px;
          height: 144px;
          border-radius: var(--ha-card-border-radius, 4px);
          flex-shrink: 0;
          background: var(--secondary-background-color);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 2.5em;
        }
        .expansion-text { flex: 1; min-width: 0; }
        .expansion-name {
          font-size: 1.05em;
          font-weight: 600;
          color: var(--primary-text-color);
          margin-bottom: 2px;
        }
        .expansion-sci {
          font-size: 0.875em;
          font-style: italic;
          color: var(--secondary-text-color);
          margin-bottom: 10px;
        }
        .metrics {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .metric {
          background: var(--secondary-background-color);
          border-radius: 6px;
          padding: 3px 8px;
          font-size: 0.78em;
          color: var(--secondary-text-color);
          white-space: nowrap;
        }
        .metric strong {
          color: var(--primary-text-color);
          font-weight: 600;
        }

        .empty {
          padding: 10px 16px;
          font-size: 0.85em;
          font-style: italic;
          color: var(--disabled-text-color);
        }
      </style>
      <ha-card>
        <div class="layout">
        ${title ? `<div class="card-header">${_esc(title)}</div>` : ""}
        <div class="list">
          ${items.length === 0
            ? `<div class="empty">No data yet</div>`
            : items.map((item, i) => `
                <div class="row" data-idx="${i}" role="button" tabindex="0" aria-expanded="${item.species === this._openSpecies ? "true" : "false"}">
                  ${item.image_url
                    ? `<img class="thumb" src="${_esc(item.image_url)}" alt="${_esc(item.species)}" loading="lazy">`
                    : `<div class="thumb-placeholder">🐦</div>`}
                  <div class="rank">${_esc(this._rank(item, i))}</div>
                  <div class="info">
                    <div class="name">${_esc(item.species)}</div>
                    ${item.scientific_name ? `<div class="sub">${_esc(item.scientific_name)}</div>` : ""}
                  </div>
                </div>
                <div class="expansion${item.species === this._openSpecies ? " is-open" : ""}" data-idx="${i}">
                  <div class="expansion-inner">
                    <div class="expansion-body">
                      ${item.image_url
                        ? `<img class="expansion-photo" src="${_esc(item.image_url)}" alt="${_esc(item.species)}">`
                        : `<div class="expansion-photo-placeholder">🐦</div>`}
                      <div class="expansion-text">
                        <div class="expansion-name">${_esc(item.species)}</div>
                        ${item.scientific_name ? `<div class="expansion-sci">${_esc(item.scientific_name)}</div>` : ""}
                        <div class="metrics">
                          ${item.count != null ? `<div class="metric"><strong>${_esc(item.count)}×</strong></div>` : ""}
                          ${this._relativeTime(item.last_seen) ? `<div class="metric">last heard <strong>${_esc(this._relativeTime(item.last_seen))}</strong></div>` : ""}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              `).join("")}
        </div>
        </div>
      </ha-card>
    `;

    const list = this.shadowRoot.querySelector(".list");
    list.addEventListener("click", (e) => {
      const row = e.target.closest(".row");
      if (row) this._toggleRow(row);
    });
    list.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const row = e.target.closest(".row");
      if (!row) return;
      e.preventDefault();  // Space would otherwise scroll the list
      this._toggleRow(row);
    });
  }

  _toggleRow(row) {
    const idx = row.dataset.idx;
    const species = this._items?.[idx]?.species ?? null;
    const panel = this.shadowRoot.querySelector(`.expansion[data-idx="${idx}"]`);
    const opening = !panel.classList.contains("is-open");
    this.shadowRoot.querySelectorAll(".expansion").forEach(el => el.classList.remove("is-open"));
    this.shadowRoot.querySelectorAll(".row").forEach(el => el.setAttribute("aria-expanded", "false"));
    if (opening) {
      panel.classList.add("is-open");
      row.setAttribute("aria-expanded", "true");
    }
    // Remember the expanded species so it survives the next poll
    // re-render — the list re-orders, so track species not index.
    this._openSpecies = opening ? species : null;
  }

  getCardSize() {
    const attrs = this._hass?.states[this._config.entity]?.attributes ?? {};
    return Math.min(attrs.detections?.length ?? 0, this._config.top) + 2;
  }

  getGridOptions() {
    // Sections grid is a 12-column scale. A ranked list wants full
    // width and height; users can shrink to half / 3 rows.
    return {
      columns: 12,
      rows: 6,
      min_columns: 6,
      min_rows: 3,
    };
  }
}

customElements.define("haikubox-bird-list-card", HaikuboxBirdListCard);

window.customCards ??= [];
window.customCards.push({
  type: "haikubox-bird-list-card",
  name: "Haikubox Bird List Card",
  description: "Ranked bird species list — works with yearly, daily, or 7-day rarity sensors.",
});
