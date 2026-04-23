function _esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

class HaikuboxBirdCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  setConfig(config) {
    if (!config.entity) throw new Error("'entity' is required");
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    const stateObj = hass?.states[this._config?.entity];
    const lastChanged = stateObj?.last_changed;
    if (lastChanged === this._lastChanged) return;
    this._lastChanged = lastChanged;
    this._render();
  }

  _relativeTime(isoString) {
    if (!isoString) return "";
    const diff = Math.floor((Date.now() - new Date(isoString)) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  _render() {
    const stateObj = this._hass?.states[this._config.entity];
    const species = stateObj?.state;
    const attrs = stateObj?.attributes ?? {};
    const empty = !species || ["unknown", "unavailable"].includes(species);

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { overflow: hidden; }
        .body { padding: 12px 16px 16px; text-align: center; }
        img {
          display: block;
          width: 100%;
          border-radius: var(--ha-card-border-radius, 4px)
            var(--ha-card-border-radius, 4px) 0 0;
        }
        .species {
          margin: 10px 0 2px;
          font-size: 1.1em;
          font-weight: 600;
          color: var(--primary-text-color);
        }
        .scientific {
          margin: 0 0 4px;
          font-size: 0.875em;
          font-style: italic;
          color: var(--secondary-text-color);
        }
        .time {
          font-size: 0.8em;
          color: var(--secondary-text-color);
        }
        .empty {
          padding: 24px 16px;
          text-align: center;
          color: var(--secondary-text-color);
          font-style: italic;
        }
      </style>
      <ha-card>
        ${empty ? `
          <div class="empty">No recent detections</div>
        ` : `
          <img src="${_esc(attrs.image_url ?? "")}" alt="${_esc(species)}">
          <div class="body">
            <div class="species">${_esc(species)}</div>
            <div class="scientific">${_esc(attrs.scientific_name ?? "")}</div>
            <div class="time">${_esc(this._relativeTime(attrs.last_seen))}</div>
          </div>
        `}
      </ha-card>
    `;
  }

  getCardSize() {
    return 4;
  }
}

customElements.define("haikubox-bird-card", HaikuboxBirdCard);

window.customCards ??= [];
window.customCards.push({
  type: "haikubox-bird-card",
  name: "Haikubox Bird Card",
  description: "Displays a Haikubox bird detection with photo, species name, and timestamp.",
});
