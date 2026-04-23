function _esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

class HaikuboxBirdListCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  setConfig(config) {
    if (!config.entity) throw new Error("'entity' is required");
    this._config = { top: 10, ...config };
  }

  set hass(hass) {
    this._hass = hass;
    const stateObj = hass?.states[this._config?.entity];
    const lastChanged = stateObj?.last_changed;
    if (lastChanged === this._lastChanged) return;
    this._lastChanged = lastChanged;
    this._render();
  }

  _rank(item, index) {
    if (item.rank != null) return `#${item.rank}`;
    return `#${index + 1}`;
  }

  _periodLabel(item) {
    if (item.rank != null) return "this year";
    if (item.rarity_score != null) return "this week";
    return "today";
  }

  _relativeTime(isoString) {
    if (!isoString) return null;
    const diff = Math.floor((Date.now() - new Date(isoString)) / 1000);
    if (diff < 60)    return `${diff}s ago`;
    if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  _render() {
    const stateObj = this._hass?.states[this._config.entity];
    const attrs = stateObj?.attributes ?? {};
    const items = (attrs.items ?? []).slice(0, this._config.top);
    const title = this._config.title ?? attrs.friendly_name ?? "";
    const maxHeight = this._config.max_height;

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 0 0 4px; }

        .card-header {
          padding: 14px 16px 10px;
          font-size: 1.15em;
          font-weight: 600;
          text-align: center;
          color: var(--primary-text-color);
          border-bottom: 1px solid var(--divider-color);
        }

        .list {
          overflow-y: auto;
          ${maxHeight ? `max-height: ${maxHeight}px;` : ""}
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
        ${title ? `<div class="card-header">${_esc(title)}</div>` : ""}
        <div class="list">
          ${items.length === 0
            ? `<div class="empty">No data yet</div>`
            : items.map((item, i) => `
                <div class="row" data-idx="${i}">
                  ${item.image_url
                    ? `<img class="thumb" src="${_esc(item.image_url)}" alt="${_esc(item.species)}" loading="lazy">`
                    : `<div class="thumb-placeholder">🐦</div>`}
                  <div class="rank">${_esc(this._rank(item, i))}</div>
                  <div class="info">
                    <div class="name">${_esc(item.species)}</div>
                    ${item.scientific_name ? `<div class="sub">${_esc(item.scientific_name)}</div>` : ""}
                  </div>
                </div>
                <div class="expansion" data-idx="${i}">
                  <div class="expansion-inner">
                    <div class="expansion-body">
                      ${item.image_url
                        ? `<img class="expansion-photo" src="${_esc(item.image_url)}" alt="${_esc(item.species)}">`
                        : `<div class="expansion-photo-placeholder">🐦</div>`}
                      <div class="expansion-text">
                        <div class="expansion-name">${_esc(item.species)}</div>
                        ${item.scientific_name ? `<div class="expansion-sci">${_esc(item.scientific_name)}</div>` : ""}
                        <div class="metrics">
                          ${item.count != null ? `<div class="metric"><strong>${item.count}×</strong> ${_esc(this._periodLabel(item))}</div>` : ""}
                          ${item.yearly_rank ? `<div class="metric">ranked <strong>#${item.yearly_rank}</strong> this year</div>` : ""}
                          ${this._relativeTime(item.last_seen) ? `<div class="metric">last heard <strong>${_esc(this._relativeTime(item.last_seen))}</strong></div>` : ""}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              `).join("")}
        </div>
      </ha-card>
    `;

    this.shadowRoot.querySelector(".list").addEventListener("click", (e) => {
      const row = e.target.closest(".row");
      if (!row) return;
      const idx = row.dataset.idx;
      const panel = this.shadowRoot.querySelector(`.expansion[data-idx="${idx}"]`);
      const opening = !panel.classList.contains("is-open");
      this.shadowRoot.querySelectorAll(".expansion").forEach(el => el.classList.remove("is-open"));
      if (opening) panel.classList.add("is-open");
    });
  }

  getCardSize() {
    const attrs = this._hass?.states[this._config.entity]?.attributes ?? {};
    return Math.min(attrs.items?.length ?? 0, this._config.top) + 2;
  }
}

customElements.define("haikubox-bird-list-card", HaikuboxBirdListCard);

window.customCards ??= [];
window.customCards.push({
  type: "haikubox-bird-list-card",
  name: "Haikubox Bird List Card",
  description: "Ranked bird species list — works with yearly, daily, or 7-day rarity sensors.",
});
