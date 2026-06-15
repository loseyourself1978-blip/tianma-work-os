(function renderStaticShell() {
  "use strict";

  const data = window.TIANMA_LDD_STATIC_SHELL_DATA;
  const app = document.getElementById("static-shell-app");
  const nav = document.getElementById("panel-nav");

  function makeElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    if (text !== undefined) {
      element.textContent = String(text);
    }
    return element;
  }

  function humanize(value) {
    return String(value).replace(/_/g, " ");
  }

  function valueForPath(source, path) {
    return path.split(".").reduce((current, key) => {
      if (current && Object.prototype.hasOwnProperty.call(current, key)) {
        return current[key];
      }
      return undefined;
    }, source);
  }

  function renderScalarList(values) {
    const list = makeElement("ul", "value-list");
    values.forEach((item) => {
      list.appendChild(makeElement("li", "", item));
    });
    return list;
  }

  function renderObject(value) {
    const container = makeElement("div", "object-view");
    Object.entries(value).forEach(([key, nestedValue]) => {
      const row = makeElement("div", "object-row");
      row.appendChild(makeElement("span", "object-key", humanize(key)));
      const cell = makeElement("div", "object-value");
      cell.appendChild(renderValue(nestedValue));
      row.appendChild(cell);
      container.appendChild(row);
    });
    return container;
  }

  function renderValue(value) {
    if (Array.isArray(value)) {
      return renderScalarList(value.map((item) => {
        if (typeof item === "object" && item !== null) {
          return Object.entries(item).map(([key, nestedValue]) => `${humanize(key)}: ${nestedValue}`).join(" | ");
        }
        return item;
      }));
    }
    if (typeof value === "object" && value !== null) {
      return renderObject(value);
    }
    return makeElement("span", "scalar-value", value);
  }

  function renderField(field) {
    const block = makeElement("div", "field-row");
    block.appendChild(makeElement("div", "field-label", humanize(field)));
    const value = valueForPath(data, field);
    const valueBlock = makeElement("div", "field-value");
    valueBlock.appendChild(renderValue(value === undefined ? "not represented in fixture" : value));
    block.appendChild(valueBlock);
    return block;
  }

  function renderPanel(panel, index) {
    const details = makeElement("details", "panel");
    details.id = panel.panel_id;
    if (index < 4) {
      details.open = true;
    }

    const summary = makeElement("summary", "panel-summary");
    summary.appendChild(makeElement("span", "panel-title", panel.title));
    summary.appendChild(makeElement("span", "panel-state", "READ ONLY"));
    details.appendChild(summary);

    const body = makeElement("div", "panel-body");
    body.appendChild(makeElement("p", "panel-purpose", panel.purpose));
    panel.fields.forEach((field) => {
      body.appendChild(renderField(field));
    });
    details.appendChild(body);
    return details;
  }

  function renderNav(panels) {
    panels.forEach((panel) => {
      const item = makeElement("a", "nav-link", panel.title);
      item.setAttribute("href", `#${panel.panel_id}`);
      nav.appendChild(item);
    });
  }

  function renderLabels() {
    const labelRegion = document.getElementById("required-labels");
    data.required_labels.forEach((label) => {
      labelRegion.appendChild(makeElement("span", "guard-label", label));
    });
  }

  function renderShell() {
    if (!data || !app || !nav) {
      return;
    }
    document.getElementById("phase").textContent = data.phase;
    document.getElementById("checkpoint").textContent = data.active_checkpoint;
    document.getElementById("readiness").textContent = data.static_shell_implementation_readiness;
    document.getElementById("mode").textContent = `${data.operating_mode} / ${data.portfolio_mode}`;
    document.getElementById("source-warning").textContent = "Embedded fixture snapshot only. No network, no credentials, no live data, no execution.";

    renderLabels();
    renderNav(data.panels);
    data.panels.forEach((panel, index) => {
      app.appendChild(renderPanel(panel, index));
    });
  }

  renderShell();
}());
