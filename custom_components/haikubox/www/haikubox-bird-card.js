function _esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Editor ────────────────────────────────────────────────────────────────────

class HaikuboxBirdCardEditor extends HTMLElement {
  // No shadow DOM — light DOM avoids isolation issues with ha-entity-picker

  setConfig(config) {
    this._config = config;
    if (!this._built) {
      this._built = true;
      this._init();
    } else {
      if (this._picker) this._picker.value = config.entity ?? "";
      if (this._action) this._action.value = config.tap_action ?? { action: "more-info" };
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._built = true;
      this._init();
    } else {
      if (this._picker) this._picker.hass = hass;
      if (this._action) this._action.hass = hass;
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

    let field;
    if (customElements.get("ha-entity-picker")) {
      field = document.createElement("ha-entity-picker");
      field.label = "Entity";
      field.setAttribute("allow-custom-entity", "");
      field.includeDomains = ["sensor"];
      if (this._hass) field.hass = this._hass;
      field.value = this._config?.entity ?? "";
      field.addEventListener("value-changed", (e) => this._fire({ entity: e.detail.value }));
    } else if (customElements.get("ha-selector")) {
      field = document.createElement("ha-selector");
      field.label = "Entity";
      field.selector = { entity: { domain: ["sensor"] } };
      if (this._hass) field.hass = this._hass;
      field.value = this._config?.entity ?? "";
      field.addEventListener("value-changed", (e) => this._fire({ entity: e.detail.value }));
    } else {
      field = document.createElement("ha-textfield");
      field.label = "Entity ID";
      field.value = this._config?.entity ?? "";
      field.addEventListener("change", (e) => this._fire({ entity: e.target.value }));
    }
    field.style.cssText = "display:block;padding:0 16px 16px";
    this._picker = field;
    this.appendChild(field);

    // Tap action — HA's standard ui-action editor when available; the
    // YAML tap_action option still works without it.
    if (customElements.get("ha-selector")) {
      const action = document.createElement("ha-selector");
      action.label = "Tap action";
      action.selector = {
        ui_action: { actions: ["more-info", "navigate", "url", "none"] },
      };
      if (this._hass) action.hass = this._hass;
      action.value = this._config?.tap_action ?? { action: "more-info" };
      action.addEventListener("value-changed", (e) => this._fire({ tap_action: e.detail.value }));
      action.style.cssText = "display:block;padding:0 16px 16px";
      this._action = action;
      this.appendChild(action);
    }
  }
}

customElements.define("haikubox-bird-card-editor", HaikuboxBirdCardEditor);

// ── Card ──────────────────────────────────────────────────────────────────────

class HaikuboxBirdCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  static getConfigElement() {
    return document.createElement("haikubox-bird-card-editor");
  }

  static getStubConfig() {
    return { entity: "", tap_action: { action: "more-info" } };
  }

  setConfig(config) {
    if (config.entity === undefined) throw new Error("'entity' is required");
    // tap_action follows HA's standard schema. Default to more-info
    // (HA's universal default for entity-bound cards); { action: "none" }
    // restores the card's previous inert behaviour.
    this._config = { tap_action: { action: "more-info" }, ...config };
  }

  set hass(hass) {
    this._hass = hass;
    const stateObj = hass?.states[this._config?.entity];
    // Gate on last_updated, not last_changed: this entity's state is a
    // species name that often stays constant across polls while the
    // attributes (image, timestamp) change. last_changed only moves when
    // .state changes, so it would freeze the card on attribute-only updates.
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

  _relativeTime(isoString) {
    if (!isoString) return "";
    // Clamp: a future timestamp (clock skew) must not show "-3s ago".
    const diff = Math.max(0, Math.floor((Date.now() - new Date(isoString)) / 1000));
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  _fillTokens(str) {
    const stateObj = this._hass?.states[this._config.entity];
    const species = stateObj?.state ?? "";
    const attrs = stateObj?.attributes ?? {};
    return String(str).replace(
      /\{(species|sp_code|scientific_name)\}/g,
      (_, key) => {
        const value =
          key === "species" ? species
          : key === "sp_code" ? (attrs.sp_code ?? "")
          : (attrs.scientific_name ?? "");
        return encodeURIComponent(value);
      },
    );
  }

  _handleTapAction() {
    const cfg = this._config.tap_action ?? { action: "more-info" };
    const action = cfg.action ?? "more-info";
    if (action === "none") return;
    if (action === "more-info") {
      const entityId = cfg.entity ?? this._config.entity;
      if (!entityId) return;
      this.dispatchEvent(new CustomEvent("hass-more-info", {
        detail: { entityId },
        bubbles: true,
        composed: true,
      }));
    } else if (action === "navigate") {
      if (!cfg.navigation_path) return;
      history.pushState(null, "", this._fillTokens(cfg.navigation_path));
      window.dispatchEvent(new Event("location-changed"));
    } else if (action === "url") {
      if (!cfg.url_path) return;
      window.open(this._fillTokens(cfg.url_path), "_blank", "noreferrer");
    }
  }

  _render() {
    const stateObj = this._hass?.states[this._config.entity];
    const species = stateObj?.state;
    const attrs = stateObj?.attributes ?? {};
    const empty = !species || ["unknown", "unavailable"].includes(species);
    const actionable = (this._config.tap_action?.action ?? "more-info") !== "none";

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
          container-type: size;
        }
        ha-card {
          overflow: hidden;
          height: 100%;
          padding: 0;
        }
        ha-card.actionable { cursor: pointer; }
        ha-card.actionable:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: -2px;
        }
        .layout {
          display: flex;
          flex-direction: column;
          height: 100%;
          overflow: hidden;
        }

        /*
         * Portrait layout — three priorities when vertical space is tight:
         *  1. Crop the photo (fill full width, but no wider than 3:2 aspect ratio)
         *  2. Drop the scientific name   [portrait B query below]
         *  3. Shrink the photo to 3:2, centre horizontally  [portrait C query below]
         */
        .img-wrap {
          flex: 0 0 auto;
          /*
           * Portrait: photo height = card width (square), but not more than
           * card height minus a minimum text area (72px covers 3 lines).
           */
          height: min(100cqw, calc(100cqh - 72px));
          width: 100%;
          align-self: center;
          overflow: hidden;
          border-radius: var(--ha-card-border-radius, 4px)
            var(--ha-card-border-radius, 4px) 0 0;
        }
        img {
          display: block;
          width: 100%;
          height: 100%;
          object-fit: cover;
        }
        .img-placeholder {
          width: 100%;
          height: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--secondary-background-color);
          font-size: 3em;
        }
        /* Body fills remaining space; justify-content centres text vertically */
        .body {
          flex: 1 1 auto;
          min-height: 0;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 10px 16px;
          text-align: center;
        }

        /* Wide layout: image left, text right */
        @container (aspect-ratio > 3/2) {
          .layout { flex-direction: row; }
          .img-wrap {
            flex: 0 0 auto;
            align-self: stretch;
            border-radius: var(--ha-card-border-radius, 4px) 0 0
              var(--ha-card-border-radius, 4px);
            width: 100cqh; /* square: width = card height */
            height: 100%;  /* override portrait square formula */
          }
          .body {
            flex: 1 1 auto;
            min-height: 0;
            align-items: flex-start;
            text-align: left;
            padding: 16px 20px;
          }
          .text-group { align-items: flex-start; }
        }

        /*
         * Portrait priority 2: drop scientific name when card is wider than ~1:1.
         * max-aspect-ratio: 3/2 limits this rule to portrait mode only.
         */
        @container (min-aspect-ratio: 1.05) and (max-aspect-ratio: 3/2) {
          .scientific { display: none; }
        }

        /*
         * Portrait priority 3: card is too short for full-width 3:2 photo + text.
         * Shrink photo to 3:2, centre horizontally.
         * 54px ≈ 2-line body (20px padding + 18px species + 13px time + 3px gap).
         */
        @container (min-aspect-ratio: 1.2) and (max-aspect-ratio: 3/2) {
          .img-wrap {
            flex: 0 0 auto;
            height: calc(100cqh - 54px);
            width: min(100cqw, calc((100cqh - 54px) * 1.5));
          }
        }

        .text-group {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 3px;
        }
        .species {
          font-size: 1.1em;
          font-weight: 600;
          color: var(--primary-text-color);
        }
        .scientific {
          font-size: 0.875em;
          font-style: italic;
          color: var(--secondary-text-color);
        }
        .time {
          font-size: 0.8em;
          color: var(--secondary-text-color);
        }

        /* Wide layout: drop scientific / shrink fonts when card is very short */
        @container (aspect-ratio > 3/2) and (max-height: 71px) {
          .scientific { display: none; }
        }
        @container (aspect-ratio > 3/2) and (max-height: 51px) {
          .species { font-size: 0.95em; }
          .time { font-size: 0.72em; }
        }
        .empty {
          padding: 24px 16px;
          text-align: center;
          color: var(--secondary-text-color);
          font-style: italic;
        }
      </style>
      <ha-card class="${actionable ? "actionable" : ""}"${actionable ? ' role="button" tabindex="0"' : ""}>
        <div class="layout">
          ${empty ? `
            <div class="empty">No recent detections</div>
          ` : `
            <div class="img-wrap">
              ${attrs.image_url
                ? `<img src="${_esc(attrs.image_url)}" alt="${_esc(species)}">`
                : `<div class="img-placeholder">🐦</div>`}
            </div>
            <div class="body">
              <div class="text-group">
                <div class="species">${_esc(species)}</div>
                <div class="scientific">${_esc(attrs.scientific_name ?? "")}</div>
                <div class="time">${_esc(this._relativeTime(attrs.last_seen))}</div>
              </div>
            </div>
          `}
        </div>
      </ha-card>
    `;

    if (actionable) {
      const card = this.shadowRoot.querySelector("ha-card");
      card.addEventListener("click", () => this._handleTapAction());
      card.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();  // Space would otherwise scroll the page
        this._handleTapAction();
      });
    }
  }

  getCardSize() {
    return 4;
  }

  getGridOptions() {
    // Sections grid is a 12-column scale (not the small scale the old
    // getLayoutOptions numbers assumed). Half-width photo card.
    return {
      columns: 6,
      rows: 4,
      min_columns: 4,
    };
  }
}

customElements.define("haikubox-bird-card", HaikuboxBirdCard);

window.customCards ??= [];
window.customCards.push({
  type: "haikubox-bird-card",
  name: "Haikubox Bird Card",
  description: "Displays a Haikubox bird detection with photo, species name, and timestamp.",
});
