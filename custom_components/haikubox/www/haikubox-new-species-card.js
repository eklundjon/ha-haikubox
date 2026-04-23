class HaikuboxNewSpeciesCard extends HTMLElement {
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
    const attrs = stateObj?.attributes ?? {};
    const newToday = attrs.new_today ?? [];
    const lifetimeCount = attrs.lifetime_species_count ?? 0;
    const [featured, ...rest] = newToday;

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { overflow: hidden; }

        img {
          display: block;
          width: 100%;
          border-radius: var(--ha-card-border-radius, 4px)
            var(--ha-card-border-radius, 4px) 0 0;
        }

        .featured {
          padding: 12px 16px 8px;
          text-align: center;
          border-bottom: 1px solid var(--divider-color);
        }
        .new-badge {
          display: inline-block;
          font-size: 0.7em;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: var(--primary-color);
          margin-bottom: 4px;
        }
        .species {
          margin: 0 0 2px;
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

        .others { padding: 4px 0; }
        .other-row {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 6px 16px;
          border-bottom: 1px solid var(--divider-color);
        }
        .other-row img {
          width: 40px;
          height: 40px;
          border-radius: 50%;
          object-fit: cover;
          flex-shrink: 0;
        }
        .other-text { flex: 1; min-width: 0; }
        .other-species {
          font-size: 0.9em;
          font-weight: 500;
          color: var(--primary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .other-scientific {
          font-size: 0.8em;
          font-style: italic;
          color: var(--secondary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .other-time {
          font-size: 0.75em;
          color: var(--secondary-text-color);
          flex-shrink: 0;
        }

        .footer {
          padding: 8px 16px;
          font-size: 0.8em;
          color: var(--secondary-text-color);
          text-align: center;
        }

        .empty {
          padding: 24px 16px 8px;
          text-align: center;
          color: var(--secondary-text-color);
          font-style: italic;
        }
      </style>
      <ha-card>
        ${featured ? `
          <img src="${featured.image_url ?? ""}" alt="${featured.species}">
          <div class="featured">
            <div class="new-badge">New species</div>
            <div class="species">${featured.species}</div>
            <div class="scientific">${featured.scientific_name ?? ""}</div>
            <div class="time">First detected ${this._relativeTime(featured.first_seen)}</div>
          </div>
          ${rest.length > 0 ? `
            <div class="others">
              ${rest.map(d => `
                <div class="other-row">
                  <img src="${d.image_url ?? ""}" alt="${d.species}">
                  <div class="other-text">
                    <div class="other-species">${d.species}</div>
                    <div class="other-scientific">${d.scientific_name ?? ""}</div>
                  </div>
                  <div class="other-time">${this._relativeTime(d.first_seen)}</div>
                </div>
              `).join("")}
            </div>
          ` : ""}
        ` : `
          <div class="empty">No new species detected yet</div>
        `}
        <div class="footer">${lifetimeCount} species heard lifetime</div>
      </ha-card>
    `;
  }

  getCardSize() {
    const newToday = this._hass?.states[this._config.entity]?.attributes?.new_today ?? [];
    return 3 + newToday.length;
  }
}

customElements.define("haikubox-new-species-card", HaikuboxNewSpeciesCard);

window.customCards ??= [];
window.customCards.push({
  type: "haikubox-new-species-card",
  name: "Haikubox New Species Card",
  description: "Highlights bird species detected for the first time on this Haikubox.",
});
