let kind = "printer";
let plugins = [];
let services = [];
let printers = [];
let devices = [];
/** @type {"service"|"lan"|null} */
let printerSource = null;
/** @type {string|null} */
let selectedPluginId = null;
/** @type {object|null} */
let existingIntegration = null;
/** @type {boolean} */
let integrationEditing = false;
/** @type {ReturnType<typeof setInterval>|null} */
let integrationStatusTimer = null;
/** @type {object|null} */
let existingService = null;
/** @type {ReturnType<typeof setInterval>|null} */
let serviceStatusTimer = null;
/** @type {string|null} */
let selectedPrinterId = null;
/** @type {ReturnType<typeof setInterval>|null} */
let printerViewTimer = null;
/** @type {"list"|"detail"|"add"|null} */
let printerView = null;
/** @type {object|null} */
let uiState = null;

function queryKind() {
  const params = new URLSearchParams(window.location.search);
  const value = (params.get("kind") || "printer").toLowerCase();
  if (value === "service" || value === "integration") return value;
  return "printer";
}

function queryWantsEdit() {
  return new URLSearchParams(window.location.search).get("edit") === "1";
}

function queryWantsConnect() {
  return new URLSearchParams(window.location.search).get("connect") === "1";
}

function queryWantsAdd() {
  return new URLSearchParams(window.location.search).get("add") === "1";
}

function queryPrinterId() {
  return new URLSearchParams(window.location.search).get("id");
}

function setPageTitle(context) {
  const label = String(context || "").trim();
  document.title = label ? `${label} — Kinkajou Bridge` : "Kinkajou Bridge";
}

function showMessage(text, ok) {
  const el = document.getElementById("message");
  el.hidden = false;
  el.className = `msg ${ok ? "ok" : "error"}`;
  el.textContent = text;
}

function fieldVisible(field, values) {
  const rules = field.visible_when || {};
  return Object.entries(rules).every(([key, expected]) => values[key] === expected);
}

function currentValues() {
  const form = document.getElementById("setup-form");
  const data = new FormData(form);
  const values = {};
  for (const [key, value] of data.entries()) {
    values[key] = value;
  }
  if (kind === "printer" && printerSource) {
    values.connection_mode = printerSource;
  }
  if (kind === "printer" && selectedPluginId) {
    values.plugin_id = selectedPluginId;
  }
  // Prefill from saved Streamer.bot config when editing (form may not have typed yet).
  if (kind === "integration" && existingIntegration?.config) {
    const cfg = existingIntegration.config;
    for (const [key, value] of Object.entries(cfg)) {
      if (values[key] == null || values[key] === "") {
        if (key === "password" && value === "***") continue;
        values[key] = value == null ? "" : String(value);
      }
    }
  }
  return values;
}

function appendHint(container, field) {
  const hintText = field.hint || field.description;
  if (hintText) {
    const hint = document.createElement("div");
    hint.className = "field-hint";
    hint.textContent = hintText;
    container.appendChild(hint);
  }

  if (field.hint_detail || field.help_url) {
    const details = document.createElement("details");
    details.className = "field-hint-detail";

    const summary = document.createElement("summary");
    summary.textContent = "How do I find this?";
    details.appendChild(summary);

    if (field.hint_detail) {
      const body = document.createElement("div");
      body.className = "field-hint-detail-body";
      body.textContent = field.hint_detail;
      details.appendChild(body);
    }

    if (field.help_url) {
      const link = document.createElement("a");
      link.href = field.help_url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.className = "field-help-link";
      link.textContent = "Open related docs";
      details.appendChild(link);
    }

    container.appendChild(details);
  }
}

function selectedPlugin() {
  if (kind === "printer" || kind === "integration" || kind === "service") {
    return plugins.find((item) => item.id === selectedPluginId);
  }
  const pluginId = document.getElementById("plugin-id").value;
  return plugins.find((item) => item.id === pluginId);
}

function compatibleServices(plugin) {
  if (!plugin || !plugin.compatible_service_ids) return [];
  const ids = new Set(plugin.compatible_service_ids);
  return services.filter((s) => ids.has(s.plugin_id));
}

function pluginsForSource() {
  if (kind !== "printer" || !printerSource) return plugins;
  if (printerSource === "service") {
    return plugins.filter(
      (p) => Array.isArray(p.compatible_service_ids) && p.compatible_service_ids.length > 0
    );
  }
  return plugins.filter((p) => p.supports_standalone !== false);
}

function fillNonPrinterPluginSelect() {
  const select = document.getElementById("plugin-id");
  // For service/integration kinds we use a visible select — recreate if needed.
  if (select.tagName !== "SELECT") return;
  select.innerHTML = "";
  for (const plugin of plugins) {
    const opt = document.createElement("option");
    opt.value = plugin.id;
    opt.textContent = plugin.name;
    select.appendChild(opt);
  }
}

function removePrinterServicePickers() {
  document.getElementById("service-picker-wrap")?.remove();
  document.getElementById("device-picker-wrap")?.remove();
  devices = [];
}

function ensurePrinterServicePickers() {
  const form = document.getElementById("setup-form");
  const anchor = document.getElementById("dynamic-fields");
  if (!document.getElementById("service-picker-wrap")) {
    const serviceWrap = document.createElement("div");
    serviceWrap.id = "service-picker-wrap";
    serviceWrap.className = "field";
    serviceWrap.innerHTML = `
      <span class="field-label">Connected service</span>
      <div id="service-display" class="readonly-value">—</div>
      <input type="hidden" id="service-instance-id" name="service_instance_id" value="" />
      <div class="field-hint" id="service-picker-hint"></div>
      <div id="service-choice-grid" class="choice-grid" hidden></div>
    `;
    form.insertBefore(serviceWrap, anchor);
  }
  if (!document.getElementById("device-picker-wrap")) {
    const deviceWrap = document.createElement("div");
    deviceWrap.id = "device-picker-wrap";
    deviceWrap.className = "field";
    deviceWrap.innerHTML = `
      <label>
        <span class="field-label">Printer from service</span>
        <select id="device-id" name="device_id" required></select>
      </label>
      <div class="field-hint" id="device-picker-hint">
        Choose a printer from the connected service. Serial is filled in automatically.
      </div>
    `;
    form.insertBefore(deviceWrap, anchor);
    document.getElementById("device-id").addEventListener("change", applyDeviceSelection);
  }
}

function setSelectedService(serviceId) {
  const hidden = document.getElementById("service-instance-id");
  const display = document.getElementById("service-display");
  if (!hidden || !display) return;
  hidden.value = serviceId || "";
  const service = services.find((s) => s.id === serviceId);
  display.textContent = service
    ? `${service.name} (${service.plugin_id})`
    : "No compatible service connected";
  refreshDevices();
}

async function refreshDevices() {
  const select = document.getElementById("device-id");
  const hint = document.getElementById("device-picker-hint");
  const serviceId = document.getElementById("service-instance-id")?.value;
  if (!select) return;
  if (kind !== "printer" || printerSource !== "service" || !serviceId) {
    select.innerHTML = "";
    devices = [];
    return;
  }
  const previous = select.value;
  select.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Select a printer…";
  select.appendChild(placeholder);
  try {
    const res = await fetch(`/v1/services/${serviceId}/devices`);
    devices = res.ok ? await res.json() : [];
  } catch {
    devices = [];
  }
  const usedSerials = bambuSerialsInUse();
  const available = devices.filter((device) => {
    const serial = String(device.serial || device.id || "").trim();
    return !serial || !usedSerials.has(serial.toLowerCase());
  });
  if (!devices.length) {
    if (hint) {
      hint.textContent =
        "No printers were returned for this service yet. Check the service connection and try again.";
    }
    select.disabled = true;
    return;
  }
  if (!available.length) {
    if (hint) {
      hint.textContent =
        "Every printer on this account is already added. Remove one from Printers to add it again.";
    }
    select.disabled = true;
    return;
  }
  select.disabled = false;
  if (hint) {
    hint.textContent =
      available.length < devices.length
        ? "Choose a printer from the connected service. Already-added serials are hidden."
        : "Choose a printer from the connected service. Serial is filled in automatically.";
  }
  for (const device of available) {
    const opt = document.createElement("option");
    opt.value = device.id;
    const serial = device.serial || device.id;
    opt.textContent = device.model
      ? `${device.name} (${device.model} · ${serial})`
      : `${device.name} · ${serial}`;
    select.appendChild(opt);
  }
  if (previous && available.some((d) => d.id === previous)) {
    select.value = previous;
  }
  applyDeviceSelection();
}

function bambuSerialsInUse() {
  const used = new Set();
  for (const printer of printers) {
    if (printer.plugin_id !== "bambu") continue;
    const serial = String(printer.identity?.serial || "").trim();
    if (serial) used.add(serial.toLowerCase());
  }
  return used;
}

function updateServicePicker() {
  const plugin = selectedPlugin();

  // Cloud printer path only — never on Streamer.bot / service setup.
  if (kind !== "printer" || printerSource !== "service" || !plugin) {
    removePrinterServicePickers();
    return;
  }

  ensurePrinterServicePickers();
  const hint = document.getElementById("service-picker-hint");
  const choiceGrid = document.getElementById("service-choice-grid");
  const matches = compatibleServices(plugin);

  choiceGrid.innerHTML = "";
  choiceGrid.hidden = true;

  if (!matches.length) {
    setSelectedService("");
    hint.innerHTML =
      'Connect a service first: <a href="/ui/setup?kind=service">Services</a>.';
    return;
  }

  if (matches.length === 1) {
    setSelectedService(matches[0].id);
    hint.textContent = "Using this connected account for credentials.";
    return;
  }

  // Multiple compatible services — pick with cards, then show the choice read-only.
  const current = document.getElementById("service-instance-id").value;
  const selected = matches.find((s) => s.id === current) || matches[0];
  setSelectedService(selected.id);
  hint.textContent = "More than one compatible service is connected — pick which account to use.";
  choiceGrid.hidden = false;
  for (const service of matches) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className =
      service.id === selected.id ? "choice-card choice-card-selected" : "choice-card";
    btn.innerHTML = `<strong>${service.name}</strong><span class="muted">${service.plugin_id}</span>`;
    btn.addEventListener("click", () => {
      setSelectedService(service.id);
      updateServicePicker();
    });
    choiceGrid.appendChild(btn);
  }
}

function applyDeviceSelection() {
  const deviceSelect = document.getElementById("device-id");
  if (!deviceSelect) return;
  const deviceId = deviceSelect.value;
  const form = document.getElementById("setup-form");
  const serialInput = form.querySelector('[name="serial"]');
  const serialDisplay = document.getElementById("serial-display");
  const nameInput = form.querySelector('[name="name"]');
  if (!deviceId) {
    if (serialInput) serialInput.value = "";
    if (serialDisplay) serialDisplay.textContent = "Select a printer above";
    return;
  }
  const device = devices.find((d) => d.id === deviceId);
  if (!device) return;
  if (serialInput && device.serial) serialInput.value = device.serial;
  if (serialDisplay && device.serial) serialDisplay.textContent = device.serial;
  if (nameInput && device.name && (!nameInput.value || nameInput.dataset.fromDevice === "1")) {
    nameInput.value = device.name;
    nameInput.dataset.fromDevice = "1";
  }
}

function renderSetupHelp(plugin) {
  const el = document.getElementById("setup-help");
  const steps = plugin?.config_schema?.setup_help || [];
  if (!steps.length) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  el.hidden = false;
  const list = steps.map((step) => `<li>${step}</li>`).join("");
  const docs = plugin.config_schema.setup_help_url
    ? `<a href="${plugin.config_schema.setup_help_url}" target="_blank" rel="noreferrer">Streamer.bot WebSocket docs</a>`
    : "";
  el.innerHTML = `<h3>Where to find these values</h3><ol>${list}</ol>${docs}`;
}

function renderFields() {
  const plugin = selectedPlugin();
  const container = document.getElementById("dynamic-fields");
  container.innerHTML = "";
  if (!plugin) {
    removePrinterServicePickers();
    renderSetupHelp(null);
    return;
  }

  const modeInput = document.getElementById("connection-mode");
  if (kind === "printer" && printerSource) {
    modeInput.value = printerSource;
  }
  if ((kind === "printer" || kind === "integration") && selectedPluginId) {
    document.getElementById("plugin-id").value = selectedPluginId;
  }

  const banner = document.getElementById("selected-type-banner");
  if (kind === "printer" && plugin) {
    banner.hidden = false;
    banner.textContent = plugin.config_schema.hint || plugin.config_schema.description || plugin.name;
  } else {
    banner.hidden = true;
  }

  renderSetupHelp(plugin);

  if (kind !== "printer" && kind !== "integration") {
    const schemaHint = plugin.config_schema.hint || plugin.config_schema.description;
    if (schemaHint) {
      const hintEl = document.createElement("div");
      hintEl.className = "schema-hint";
      hintEl.textContent = schemaHint;
      container.appendChild(hintEl);
    }
  }

  const values = currentValues();
  for (const field of plugin.config_schema.fields) {
    if (!(field.key in values) && field.default != null) {
      values[field.key] = String(field.default);
    }
  }
  if (kind === "printer" && printerSource) {
    values.connection_mode = printerSource;
  }

  for (const field of plugin.config_schema.fields) {
    if (kind === "printer" && field.key === "connection_mode") continue;
    if (!fieldVisible(field, values)) continue;

    // Cloud path: serial comes from the selected service printer — show, don't edit.
    if (kind === "printer" && printerSource === "service" && field.key === "serial") {
      const wrap = document.createElement("div");
      wrap.className = "field";
      const title = document.createElement("span");
      title.className = "field-label";
      title.textContent = field.label;
      wrap.appendChild(title);
      const display = document.createElement("div");
      display.id = "serial-display";
      display.className = "readonly-value";
      display.textContent = values.serial || "Select a printer above";
      wrap.appendChild(display);
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "serial";
      hidden.value = values.serial || "";
      hidden.required = true;
      wrap.appendChild(hidden);
      const hint = document.createElement("div");
      hint.className = "field-hint";
      hint.textContent = "Taken from the printer you pick above.";
      wrap.appendChild(hint);
      container.appendChild(wrap);
      continue;
    }

    const wrap = document.createElement("div");
    wrap.className = "field";

    const label = document.createElement("label");
    const title = document.createElement("span");
    title.className = "field-label";
    title.textContent = field.label + (field.required ? " *" : "");
    label.appendChild(title);

    let input;
    if (field.type === "select") {
      input = document.createElement("select");
      for (const option of field.options || []) {
        const opt = document.createElement("option");
        opt.value = option.value;
        opt.textContent = option.label;
        if (String(field.default) === option.value || values[field.key] === option.value) {
          opt.selected = true;
        }
        input.appendChild(opt);
      }
      input.addEventListener("change", () => {
        renderFields();
        updateServicePicker();
      });
    } else {
      input = document.createElement("input");
      input.type = field.type === "secret" ? "password" : field.type === "number" ? "number" : "text";
      const editingSecret =
        field.type === "secret" && kind === "integration" && !!existingIntegration;
      if (editingSecret) {
        input.placeholder = "Leave blank to keep current password";
        input.autocomplete = "new-password";
      } else {
        if (field.placeholder) input.placeholder = field.placeholder;
        if (field.default != null && values[field.key] == null) {
          input.value = field.default;
        }
        if (values[field.key] != null && values[field.key] !== "***") {
          input.value = values[field.key];
        }
      }
      if (field.key === "name") {
        input.addEventListener("input", () => {
          input.dataset.fromDevice = "0";
        });
      }
    }
    input.name = field.key;
    input.required = !!field.required && fieldVisible(field, values);
    label.appendChild(input);
    wrap.appendChild(label);
    appendHint(wrap, field);
    container.appendChild(wrap);
  }

  if (kind === "printer" && printerSource === "service") {
    updateServicePicker();
  } else {
    removePrinterServicePickers();
  }
}

function renderTypeChoices() {
  const container = document.getElementById("printer-type-choices");
  container.innerHTML = "";
  const options = pluginsForSource();
  if (!options.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent =
      printerSource === "service"
        ? "No printer types support cloud services yet."
        : "No standalone printer types are installed.";
    container.appendChild(empty);
    return;
  }
  for (const plugin of options) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "choice-card";
    const schema = plugin.config_schema || {};
    const description = schema.description || schema.hint || "";
    const examples = Array.isArray(schema.examples)
      ? schema.examples.filter((item) => String(item || "").trim())
      : [];
    const examplesHtml = examples.length
      ? `<span class="choice-examples muted">Examples: ${examples
          .map((item) => escapeHtml(String(item)))
          .join(" · ")}</span>`
      : "";
    btn.innerHTML = `<strong>${escapeHtml(plugin.name)}</strong><span class="muted">${escapeHtml(
      description
    )}</span>${examplesHtml}`;
    btn.addEventListener("click", () => setPrinterType(plugin.id));
    container.appendChild(btn);
  }
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setPrinterSource(source) {
  if (source === "service" && !services.length) return;
  printerView = "add";
  printerSource = source;
  selectedPluginId = null;
  document.getElementById("printer-list-panel").hidden = true;
  document.getElementById("printer-detail-panel").hidden = true;
  document.getElementById("printer-source-panel").hidden = true;
  document.getElementById("setup-panel").hidden = true;
  document.getElementById("printer-type-panel").hidden = false;
  document.getElementById("connection-mode").value = source;
  document.getElementById("hero-lead").textContent =
    source === "service"
      ? "Choose which printer protocol to use with a connected service."
      : "Choose which host software this printer uses on your network.";
  renderTypeChoices();
}

function setPrinterType(pluginId) {
  printerView = "add";
  selectedPluginId = pluginId;
  document.getElementById("printer-list-panel").hidden = true;
  document.getElementById("printer-detail-panel").hidden = true;
  document.getElementById("plugin-id").value = pluginId;
  document.getElementById("printer-type-panel").hidden = true;
  document.getElementById("setup-panel").hidden = false;
  document.getElementById("back-to-source").hidden = false;
  document.getElementById("back-to-source").textContent = "Change type";
  const plugin = plugins.find((p) => p.id === pluginId);
  document.getElementById("panel-title").textContent = plugin
    ? plugin.name
    : printerSource === "service"
      ? "Cloud printer"
      : "Standalone printer";
  document.getElementById("hero-lead").textContent =
    printerSource === "service"
      ? "Select a connected service, then enter this printer’s details."
      : "Enter connection details for this printer on your network.";
  renderFields();
}

function updateCloudViaServiceAvailability() {
  const btn = document.getElementById("choose-cloud");
  const hint = document.getElementById("choose-cloud-hint");
  if (!btn) return;
  const enabled = services.length > 0;
  btn.disabled = !enabled;
  btn.classList.toggle("choice-card-disabled", !enabled);
  btn.setAttribute("aria-disabled", enabled ? "false" : "true");
  if (hint) {
    hint.textContent = enabled
      ? "Pick a connected account (for example Bambu Lab) and add a printer from that service."
      : "Connect a service first (Services), then you can add printers from that account.";
  }
}

function showPrinterSourceChooser() {
  printerView = "add";
  printerSource = null;
  selectedPluginId = null;
  stopPrinterViewPolling();
  document.getElementById("printer-list-panel").hidden = true;
  document.getElementById("printer-detail-panel").hidden = true;
  document.getElementById("printer-source-panel").hidden = false;
  document.getElementById("printer-type-panel").hidden = true;
  document.getElementById("service-status-panel").hidden = true;
  document.getElementById("integration-status-panel").hidden = true;
  document.getElementById("setup-panel").hidden = true;
  document.getElementById("back-to-source").hidden = true;
  document.getElementById("connection-mode").value = "";
  document.getElementById("plugin-id").value = "";
  document.getElementById("message").hidden = true;
  document.getElementById("panel-title").textContent = "Printer";
  document.getElementById("hero-title").textContent = "Add a printer";
  setPageTitle("Add a printer");
  document.getElementById("hero-lead").textContent =
    "First choose whether this printer comes from a connected cloud service or is standalone on your LAN.";
  const cancelAdd = document.getElementById("cancel-add-printer-btn");
  if (cancelAdd) cancelAdd.hidden = printers.length === 0;
  updateCloudViaServiceAvailability();
}

function showPrinterTypeChooser() {
  printerView = "add";
  selectedPluginId = null;
  document.getElementById("printer-list-panel").hidden = true;
  document.getElementById("printer-detail-panel").hidden = true;
  document.getElementById("printer-source-panel").hidden = true;
  document.getElementById("printer-type-panel").hidden = false;
  document.getElementById("setup-panel").hidden = true;
  document.getElementById("plugin-id").value = "";
  document.getElementById("message").hidden = true;
  renderTypeChoices();
}

function fmtTemp(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${Number(value).toFixed(1)}°C`;
}

function fmtProgress(job) {
  if (!job || job.progress == null) return "—";
  const pct = Number(job.progress).toFixed(0);
  if (job.remaining_seconds == null) return `${pct}%`;
  const mins = Math.max(0, Math.round(Number(job.remaining_seconds) / 60));
  return `${pct}% · ~${mins} min left`;
}

function printerModeLabel(printer) {
  const identity = printer.identity || {};
  const mode = identity.connection_mode || "—";
  const host = identity.host;
  let modeLabel = String(mode).toUpperCase();
  if (mode === "lan" && host) modeLabel = `LAN · ${host}`;
  else if (mode === "service") modeLabel = "SERVICE";
  if (printer.service_instance_id) modeLabel += " · linked";
  return modeLabel;
}

function stopPrinterViewPolling() {
  if (printerViewTimer != null) {
    clearInterval(printerViewTimer);
    printerViewTimer = null;
  }
}

function startPrinterViewPolling() {
  stopPrinterViewPolling();
  printerViewTimer = setInterval(() => {
    if (kind !== "printer") return;
    if (printerView === "list") {
      refreshPrinters().then(renderPrinterList);
    } else if (printerView === "detail" && selectedPrinterId) {
      refreshPrinters().then(() => renderPrinterDetail(selectedPrinterId));
    }
  }, 5000);
}

async function refreshPrinters() {
  try {
    const res = await fetch("/v1/printers");
    printers = res.ok ? await res.json() : [];
  } catch {
    printers = [];
  }
  return printers;
}

function hidePrinterAddPanels() {
  document.getElementById("printer-source-panel").hidden = true;
  document.getElementById("printer-type-panel").hidden = true;
  document.getElementById("setup-panel").hidden = true;
  document.getElementById("back-to-source").hidden = true;
}

function renderPrinterList() {
  printerView = "list";
  selectedPrinterId = null;
  stopPrinterViewPolling();
  hidePrinterAddPanels();
  document.getElementById("printer-detail-panel").hidden = true;
  const panel = document.getElementById("printer-list-panel");
  const list = document.getElementById("printer-setup-list");
  panel.hidden = false;
  list.innerHTML = "";

  document.getElementById("hero-title").textContent = "Printers";
  setPageTitle("Printers");
  document.getElementById("hero-lead").textContent =
    "Bridge is monitoring these printers. Open one for details, or add another.";
  const listMsg = document.getElementById("printer-list-message");
  if (listMsg && !listMsg.textContent) listMsg.hidden = true;

  for (const printer of printers) {
    const status = printer.status || {};
    const connection = status.connection || "disconnected";
    const temps = status.temperatures || {};
    const job = status.job || {};
    const printState = status.print_state || "unknown";
    const card = document.createElement("article");
    card.className = "printer-card";
    card.innerHTML = `
      <div class="printer-card-head">
        <div>
          <h3></h3>
          <div class="muted"></div>
        </div>
        <span class="${badgeClass(connection)}"></span>
      </div>
      <dl class="status-grid">
        <div><dt>Print state</dt><dd></dd></div>
        <div><dt>Progress</dt><dd></dd></div>
        <div><dt>Job</dt><dd></dd></div>
        <div><dt>Nozzle</dt><dd></dd></div>
        <div><dt>Bed</dt><dd></dd></div>
      </dl>
      <div class="actions" style="margin-top: 0.75rem;">
        <a class="btn btn-secondary" href=""></a>
      </div>
    `;
    card.querySelector("h3").textContent = printer.name;
    card.querySelector(".muted").textContent =
      `${printer.plugin_id} · ${printerModeLabel(printer)}`;
    card.querySelector(".badge").textContent = connection;
    const dds = card.querySelectorAll("dd");
    dds[0].textContent = printState;
    dds[1].textContent = fmtProgress(job);
    dds[2].textContent = job.name || "—";
    dds[3].textContent = `${fmtTemp(temps.nozzle_c)} / ${fmtTemp(temps.nozzle_target_c)}`;
    dds[4].textContent = `${fmtTemp(temps.bed_c)} / ${fmtTemp(temps.bed_target_c)}`;
    const link = card.querySelector("a");
    link.href = `/ui/setup?kind=printer&id=${encodeURIComponent(printer.id)}`;
    link.textContent = "Details";
    if (status.message) {
      const note = document.createElement("p");
      note.className = "status-note";
      note.textContent = status.message;
      card.insertBefore(note, card.querySelector(".actions"));
    }
    list.appendChild(card);
  }

  if (window.history?.replaceState) {
    window.history.replaceState({}, "", "/ui/setup?kind=printer");
  }
  startPrinterViewPolling();
}

function renderPrinterDetail(printerId) {
  const printer = printers.find((item) => item.id === printerId);
  if (!printer) {
    selectedPrinterId = null;
    if (printers.length) renderPrinterList();
    else showPrinterSourceChooser();
    return;
  }

  printerView = "detail";
  selectedPrinterId = printerId;
  hidePrinterAddPanels();
  document.getElementById("printer-list-panel").hidden = true;
  const panel = document.getElementById("printer-detail-panel");
  panel.hidden = false;

  const status = printer.status || {};
  const identity = printer.identity || {};
  const temps = status.temperatures || {};
  const job = status.job || {};
  const connection = status.connection || "disconnected";

  document.getElementById("printer-detail-title").textContent = printer.name;
  const badge = document.getElementById("printer-detail-badge");
  badge.className = badgeClass(connection);
  badge.textContent = connection;
  document.getElementById("printer-detail-subtitle").textContent =
    `${printer.plugin_id} · ${printerModeLabel(printer)}`;

  const grid = document.getElementById("printer-detail-grid");
  grid.innerHTML = "";
  const rows = [
    ["Print state", status.print_state || "unknown"],
    ["Progress", fmtProgress(job)],
    ["Job", job.name || "—"],
    ["Nozzle", `${fmtTemp(temps.nozzle_c)} / ${fmtTemp(temps.nozzle_target_c)}`],
    ["Bed", `${fmtTemp(temps.bed_c)} / ${fmtTemp(temps.bed_target_c)}`],
    ["Serial", identity.serial || "—"],
    ["Mode", printerModeLabel(printer)],
    ["Enabled", printer.enabled ? "Yes" : "No"],
  ];
  for (const [label, value] of rows) {
    const cell = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    cell.appendChild(dt);
    cell.appendChild(dd);
    grid.appendChild(cell);
  }

  const msg = document.getElementById("printer-detail-message");
  if (status.message) {
    msg.hidden = false;
    msg.textContent = status.message;
  } else {
    msg.hidden = true;
    msg.textContent = "";
  }

  fillPrinterConnectInfo(printer);

  document.getElementById("hero-title").textContent = printer.name;
  setPageTitle(printer.name);
  document.getElementById("hero-lead").textContent =
    "Live status for this printer. Use the connect info below for overlays and Streamer.bot.";

  if (window.history?.replaceState) {
    window.history.replaceState(
      {},
      "",
      `/ui/setup?kind=printer&id=${encodeURIComponent(printerId)}`
    );
  }
  startPrinterViewPolling();
}

function apiBaseFromState() {
  return (uiState?.api_base_url || window.location.origin).replace(/\/$/, "");
}

function overlaysDocsFromState() {
  return (
    uiState?.overlays_docs_url ||
    "https://kinkajou.dev/bridge/user/overlays/"
  ).replace(/\/?$/, "/");
}

function eventsWsUrl(apiBase) {
  try {
    const u = new URL(apiBase);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.pathname = "/v1/events";
    u.search = "";
    u.hash = "";
    return u.toString();
  } catch {
    return "ws://127.0.0.1:29067/v1/events";
  }
}

function fillPrinterConnectInfo(printer) {
  const apiBase = apiBaseFromState();
  const id = printer.id;
  const overviewUrl =
    `${apiBase}/bridge/overview/?printer=${encodeURIComponent(id)}`;
  const compactUrl =
    `${apiBase}/bridge/compact/?printer=${encodeURIComponent(id)}`;

  document.getElementById("printer-connect-id").textContent = id;
  document.getElementById("printer-connect-api").textContent = apiBase;
  document.getElementById("printer-connect-ws").textContent = eventsWsUrl(apiBase);

  const overview = document.getElementById("printer-overlay-overview");
  overview.href = overviewUrl;
  overview.textContent = overviewUrl;
  overview.removeAttribute("title");

  const compact = document.getElementById("printer-overlay-compact");
  compact.href = compactUrl;
  compact.textContent = compactUrl;
  compact.removeAttribute("title");

  const docs = document.getElementById("printer-overlays-docs");
  const docsUrl = overlaysDocsFromState();
  docs.href = docsUrl;
  docs.textContent = docsUrl.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

async function copyPrinterId() {
  const id = document.getElementById("printer-connect-id")?.textContent?.trim();
  if (!id || id === "—") return;
  const btn = document.getElementById("copy-printer-id-btn");
  try {
    await navigator.clipboard.writeText(id);
    if (btn) {
      const prev = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(() => {
        btn.textContent = prev || "Copy";
      }, 1200);
    }
  } catch {
    window.prompt("Copy printer id:", id);
  }
}

function beginAddPrinter() {
  stopPrinterViewPolling();
  if (window.history?.replaceState) {
    window.history.replaceState({}, "", "/ui/setup?kind=printer&add=1");
  }
  showPrinterSourceChooser();
}

async function removeSelectedPrinter() {
  if (!selectedPrinterId) return;
  const printer = printers.find((item) => item.id === selectedPrinterId);
  const name = printer?.name || "this printer";
  if (!window.confirm(`Remove ${name}? Bridge will stop monitoring it.`)) {
    return;
  }
  const msg = document.getElementById("printer-detail-message");
  try {
    const res = await fetch(`/v1/printers/${selectedPrinterId}`, { method: "DELETE" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      msg.hidden = false;
      msg.textContent = body.detail || "Could not remove printer.";
      return;
    }
    selectedPrinterId = null;
    await refreshPrinters();
    if (printers.length) {
      renderPrinterList();
      const note = document.getElementById("printer-list-message");
      note.hidden = false;
      note.textContent = `${name} removed.`;
    } else {
      showPrinterSourceChooser();
    }
  } catch {
    msg.hidden = false;
    msg.textContent = "Could not remove printer.";
  }
}

function enterPrinterKind() {
  const printerId = queryPrinterId();
  if (printerId) {
    renderPrinterDetail(printerId);
    return;
  }
  if (queryWantsAdd() || !printers.length) {
    showPrinterSourceChooser();
    return;
  }
  renderPrinterList();
}

function ensurePluginSelectForNonPrinter() {
  const label = document.getElementById("plugin-label");
  let select = document.getElementById("plugin-id");
  if (select.tagName === "SELECT") return;
  const newSelect = document.createElement("select");
  newSelect.id = "plugin-id";
  newSelect.name = "plugin_id";
  newSelect.required = true;
  select.replaceWith(newSelect);
  label.hidden = false;
  label.appendChild(newSelect);
  newSelect.addEventListener("change", renderFields);
}

function ensureHiddenPluginInputForPrinter() {
  const label = document.getElementById("plugin-label");
  let el = document.getElementById("plugin-id");
  if (el.tagName === "INPUT") {
    label.hidden = true;
    return;
  }
  const hidden = document.createElement("input");
  hidden.type = "hidden";
  hidden.id = "plugin-id";
  hidden.name = "plugin_id";
  hidden.value = "";
  el.replaceWith(hidden);
  label.hidden = true;
}

function badgeClass(connection) {
  if (connection === "connected") return "badge ok";
  if (connection === "connecting") return "badge warn";
  if (connection === "error") return "badge bad";
  return "badge";
}

function stopIntegrationStatusPolling() {
  if (integrationStatusTimer != null) {
    clearInterval(integrationStatusTimer);
    integrationStatusTimer = null;
  }
}

function startIntegrationStatusPolling() {
  stopIntegrationStatusPolling();
  integrationStatusTimer = setInterval(() => {
    if (kind === "integration" && existingIntegration && !integrationEditing) {
      refreshExistingIntegration().then(renderIntegrationStatus);
    }
  }, 4000);
}

function stopServiceStatusPolling() {
  if (serviceStatusTimer != null) {
    clearInterval(serviceStatusTimer);
    serviceStatusTimer = null;
  }
}

function startServiceStatusPolling() {
  stopServiceStatusPolling();
  serviceStatusTimer = setInterval(() => {
    if (kind === "service" && existingService) {
      refreshExistingService().then(renderServiceStatus);
    }
  }, 4000);
}

async function refreshExistingService() {
  try {
    const res = await fetch("/v1/services");
    const list = res.ok ? await res.json() : [];
    services = list;
    existingService =
      list.find((item) => item.plugin_id === "bambu_cloud") || list[0] || null;
  } catch {
    existingService = null;
  }
  return existingService;
}

function renderServiceStatus() {
  const panel = document.getElementById("service-status-panel");
  const setupPanel = document.getElementById("setup-panel");
  if (!existingService) {
    panel.hidden = true;
    stopServiceStatusPolling();
    showServiceSetupForm();
    return;
  }

  panel.hidden = false;
  setupPanel.hidden = true;

  const status = existingService.status || {};
  const connection = status.connection || "disconnected";
  const badge = document.getElementById("service-status-badge");
  badge.className = badgeClass(connection);
  badge.textContent = connection;

  const plugin =
    plugins.find((p) => p.id === existingService.plugin_id) ||
    plugins.find((p) => p.id === "bambu_cloud");
  const title = document.getElementById("service-status-title");
  title.textContent =
    existingService.name || plugin?.name || plugin?.config_schema?.title || "Service";

  const cfg = existingService.config || {};
  const fields = plugin?.config_schema?.fields || [];
  const view = document.getElementById("service-config-view");
  view.innerHTML = "";
  for (const field of fields) {
    const raw = cfg[field.key];
    let display = "—";
    if (field.type === "secret") {
      display = raw === "***" || (raw != null && raw !== "") ? "Configured" : "Not set";
    } else if (field.type === "select" && Array.isArray(field.options)) {
      const opt = field.options.find((o) => o.value === raw);
      display = opt ? opt.label : raw != null && raw !== "" ? String(raw) : "—";
    } else if (raw != null && raw !== "") {
      display = String(raw);
    }
    const cell = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = field.label;
    const dd = document.createElement("dd");
    dd.textContent = display;
    cell.appendChild(dt);
    cell.appendChild(dd);
    view.appendChild(cell);
  }

  const msg = document.getElementById("service-status-message");
  if (status.message) {
    msg.hidden = false;
    msg.textContent = status.message;
  } else {
    msg.hidden = true;
    msg.textContent = "";
  }

  document.getElementById("hero-title").textContent = "Services";
  setPageTitle("Services");
  document.getElementById("hero-lead").textContent =
    "Account-level connections. Disconnect here when you no longer need this cloud account.";
  startServiceStatusPolling();
}

function showServiceSetupForm() {
  stopServiceStatusPolling();
  document.getElementById("service-status-panel").hidden = true;
  document.getElementById("setup-panel").hidden = false;
  document.getElementById("cancel-edit-btn").hidden = true;
  applyKindCopy();
  document.getElementById("submit-btn").textContent = "Connect service";
  document.getElementById("message").hidden = true;
  renderFields();
}

async function disconnectService() {
  if (!existingService) return;
  const name = existingService.name || "this service";
  if (!window.confirm(`Disconnect ${name}? Printers that use this service must be removed first.`)) {
    return;
  }
  const msg = document.getElementById("service-status-message");
  try {
    const res = await fetch(`/v1/services/${existingService.id}`, { method: "DELETE" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      msg.hidden = false;
      msg.textContent = body.detail || "Could not disconnect service.";
      return;
    }
    existingService = null;
    await refreshExistingService();
    showServiceSetupForm();
    showMessage("Service disconnected.", true);
  } catch {
    msg.hidden = false;
    msg.textContent = "Could not disconnect service.";
  }
}

async function refreshExistingIntegration() {
  try {
    const res = await fetch("/v1/integrations");
    const list = res.ok ? await res.json() : [];
    existingIntegration =
      list.find((item) => item.plugin_id === "streamerbot") || list[0] || null;
  } catch {
    existingIntegration = null;
  }
  return existingIntegration;
}

function renderIntegrationStatus() {
  const panel = document.getElementById("integration-status-panel");
  const setupPanel = document.getElementById("setup-panel");
  const cancelBtn = document.getElementById("cancel-edit-btn");
  if (!existingIntegration) {
    panel.hidden = true;
    setupPanel.hidden = false;
    cancelBtn.hidden = true;
    stopIntegrationStatusPolling();
    return;
  }

  panel.hidden = false;
  setupPanel.hidden = true;
  cancelBtn.hidden = true;
  integrationEditing = false;

  const status = existingIntegration.status || {};
  const connection = status.connection || "disconnected";
  const badge = document.getElementById("integration-status-badge");
  badge.className = badgeClass(connection);
  badge.textContent = connection;

  const cfg = existingIntegration.config || {};
  const plugin = selectedPlugin() || plugins.find((p) => p.id === "streamerbot");
  const fields = plugin?.config_schema?.fields || [];
  const view = document.getElementById("integration-config-view");
  view.innerHTML = "";
  for (const field of fields) {
    const raw = cfg[field.key];
    let display = "—";
    if (field.type === "secret") {
      display = raw === "***" || (raw != null && raw !== "") ? "Configured" : "Not set";
    } else if (raw != null && raw !== "") {
      display = String(raw);
    }
    const cell = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = field.label;
    const dd = document.createElement("dd");
    dd.textContent = display;
    cell.appendChild(dt);
    cell.appendChild(dd);
    view.appendChild(cell);
  }

  const msg = document.getElementById("integration-status-message");
  if (status.message) {
    msg.hidden = false;
    msg.textContent = status.message;
  } else {
    msg.hidden = true;
    msg.textContent = "";
  }

  document.getElementById("hero-title").textContent = "Streamer.bot";
  setPageTitle("Streamer.bot");
  document.getElementById("hero-lead").textContent =
    "Events from every printer become DoAction calls named Kinkajou.{event_type}.";
  document.getElementById("panel-title").textContent = "Streamer.bot";
  startIntegrationStatusPolling();
}

function showIntegrationEditForm() {
  if (!existingIntegration) return;
  integrationEditing = true;
  stopIntegrationStatusPolling();
  document.getElementById("integration-status-panel").hidden = true;
  document.getElementById("setup-panel").hidden = false;
  document.getElementById("cancel-edit-btn").hidden = false;
  document.getElementById("hero-title").textContent = "Edit Streamer.bot Connection";
  setPageTitle("Edit Streamer.bot");
  document.getElementById("hero-lead").textContent =
    "Update the WebSocket connection. Leave the password blank to keep the current value.";
  document.getElementById("panel-title").textContent = "Edit connection";
  document.getElementById("submit-btn").textContent = "Save changes";
  document.getElementById("message").hidden = true;
  renderFields();
}

function showIntegrationSetupForm() {
  integrationEditing = true;
  stopIntegrationStatusPolling();
  document.getElementById("integration-status-panel").hidden = true;
  document.getElementById("setup-panel").hidden = false;
  document.getElementById("cancel-edit-btn").hidden = !existingIntegration;
  document.getElementById("hero-title").textContent = existingIntegration
    ? "Edit Streamer.bot Connection"
    : "Streamer.bot";
  setPageTitle(existingIntegration ? "Edit Streamer.bot" : "Streamer.bot");
  document.getElementById("submit-btn").textContent = existingIntegration
    ? "Save changes"
    : "Save connection";
  renderFields();
}

function applyKindCopy() {
  const copy = {
    service: {
      kicker: "Service setup",
      title: "Services",
      lead: "Account-level connections (for example Bambu Lab cloud). Connect once, then add printers from the account.",
      panel: "Bambu Lab",
      submit: "Connect service",
      plugin: "Service",
    },
    printer: {
      kicker: "Printer setup",
      title: "Printers",
      lead: "Review connected printers, open one for details, or add another from a service or LAN.",
      panel: "Printer",
      submit: "Save printer",
      plugin: "Printer plugin",
    },
    integration: {
      kicker: "Streamer.bot",
      title: "Streamer.bot",
      lead: "One Streamer.bot connection for Bridge. Events from every printer — any cloud service or standalone host — become DoAction calls named Kinkajou.{event_type}.",
      panel: "Streamer.bot",
      submit: "Save connection",
      plugin: "Integration",
    },
  }[kind];

  document.getElementById("hero-kicker").textContent = copy.kicker;
  document.getElementById("hero-title").textContent = copy.title;
  setPageTitle(copy.title);
  document.getElementById("hero-lead").textContent = copy.lead;
  document.getElementById("panel-title").textContent = copy.panel;
  document.getElementById("submit-btn").textContent = copy.submit;
  document.getElementById("plugin-label-text").textContent = copy.plugin;

  document.getElementById("link-service").className =
    kind === "service" ? "btn btn-primary" : "btn btn-secondary";
  document.getElementById("link-printer").className =
    kind === "printer" ? "btn btn-primary" : "btn btn-secondary";
  document.getElementById("link-service").textContent = "Services";
  document.getElementById("link-printer").textContent = "Printers";
  document.getElementById("link-integration").className =
    kind === "integration" ? "btn btn-primary" : "btn btn-secondary";
  document.getElementById("link-integration").textContent = "Streamer.bot";
}

async function init() {
  kind = queryKind();
  applyKindCopy();

  const stateRes = await fetch("/v1/ui/state");
  uiState = await stateRes.json();
  document.getElementById("docs-link").href = uiState.docs_url || "https://kinkajou.dev/bridge/";

  const pluginUrl =
    kind === "service"
      ? "/v1/services/plugins"
      : kind === "integration"
        ? "/v1/integrations/plugins"
        : "/v1/printers/plugins";
  const [pluginRes, serviceRes, printerRes] = await Promise.all([
    fetch(pluginUrl),
    fetch("/v1/services"),
    fetch("/v1/printers"),
  ]);
  plugins = await pluginRes.json();
  services = serviceRes.ok ? await serviceRes.json() : [];
  printers = printerRes.ok ? await printerRes.json() : [];

  document.getElementById("choose-cloud").addEventListener("click", () => setPrinterSource("service"));
  document.getElementById("choose-standalone").addEventListener("click", () => setPrinterSource("lan"));
  document.getElementById("back-to-source").addEventListener("click", () => {
    if (kind === "printer" && printerSource) showPrinterTypeChooser();
    else showPrinterSourceChooser();
  });
  document
    .getElementById("back-to-source-from-type")
    .addEventListener("click", showPrinterSourceChooser);
  document.getElementById("edit-integration-btn").addEventListener("click", showIntegrationEditForm);
  document.getElementById("disconnect-service-btn").addEventListener("click", disconnectService);
  document.getElementById("add-printer-btn").addEventListener("click", beginAddPrinter);
  document.getElementById("remove-printer-btn").addEventListener("click", removeSelectedPrinter);
  document.getElementById("copy-printer-id-btn").addEventListener("click", copyPrinterId);
  document.getElementById("back-to-printer-list-btn").addEventListener("click", () => {
    renderPrinterList();
  });
  document.getElementById("cancel-add-printer-btn").addEventListener("click", () => {
    if (printers.length) renderPrinterList();
    else showPrinterSourceChooser();
  });
  document.getElementById("cancel-edit-btn").addEventListener("click", () => {
    if (existingIntegration) renderIntegrationStatus();
  });

  if (kind === "printer") {
    ensureHiddenPluginInputForPrinter();
    enterPrinterKind();
  } else if (kind === "integration") {
    document.getElementById("printer-list-panel").hidden = true;
    document.getElementById("printer-detail-panel").hidden = true;
    document.getElementById("printer-source-panel").hidden = true;
    document.getElementById("printer-type-panel").hidden = true;
    document.getElementById("service-status-panel").hidden = true;
    document.getElementById("back-to-source").hidden = true;
    ensureHiddenPluginInputForPrinter();
    removePrinterServicePickers();
    const sb = plugins.find((p) => p.id === "streamerbot") || plugins[0];
    if (sb) {
      selectedPluginId = sb.id;
      document.getElementById("plugin-id").value = sb.id;
    }
    await refreshExistingIntegration();
    if (existingIntegration && !queryWantsEdit()) {
      renderIntegrationStatus();
    } else {
      showIntegrationSetupForm();
    }
  } else {
    document.getElementById("printer-list-panel").hidden = true;
    document.getElementById("printer-detail-panel").hidden = true;
    document.getElementById("printer-source-panel").hidden = true;
    document.getElementById("printer-type-panel").hidden = true;
    document.getElementById("integration-status-panel").hidden = true;
    document.getElementById("back-to-source").hidden = true;
    ensureHiddenPluginInputForPrinter();
    removePrinterServicePickers();
    const bambu = plugins.find((p) => p.id === "bambu_cloud") || plugins[0];
    if (bambu) {
      selectedPluginId = bambu.id;
      document.getElementById("plugin-id").value = bambu.id;
    }
    await refreshExistingService();
    if (existingService && !queryWantsConnect()) {
      renderServiceStatus();
    } else {
      showServiceSetupForm();
    }
  }
}

document.getElementById("setup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = currentValues();
  const pluginId = values.plugin_id;
  const plugin = plugins.find((item) => item.id === pluginId);
  if (!plugin) return;

  const config = {};
  for (const field of plugin.config_schema.fields) {
    if (kind === "printer" && field.key === "connection_mode") {
      config.connection_mode = printerSource;
      continue;
    }
    if (!fieldVisible(field, values)) continue;
    if (values[field.key] != null && values[field.key] !== "") {
      config[field.key] = values[field.key];
    }
  }
  if (kind === "printer" && printerSource) {
    config.connection_mode = printerSource;
  }

  const name = config.name || plugin.name;
  try {
    if (kind === "service") {
      const res = await fetch("/v1/services", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          plugin_id: pluginId,
          config,
          enabled: true,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        showMessage(body.detail || "Could not connect service.", false);
        return;
      }
      await fetch("/v1/ui/welcome/complete", { method: "POST" });
      await refreshExistingService();
      renderServiceStatus();
      const note = document.getElementById("service-status-message");
      note.hidden = false;
      note.textContent = "Service connected.";
      if (window.history?.replaceState) {
        window.history.replaceState({}, "", "/ui/setup?kind=service");
      }
      return;
    }

    if (kind === "integration") {
      if (config.port != null && config.port !== "") {
        config.port = Number(config.port);
      }
      delete config.name;
      if (config.password === "" || config.password === "***") {
        delete config.password;
      }
      const res = await fetch("/v1/integrations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "Streamer.bot",
          plugin_id: "streamerbot",
          config,
          enabled: true,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        showMessage(body.detail || "Could not save Streamer.bot connection.", false);
        return;
      }
      await fetch("/v1/ui/welcome/complete", { method: "POST" });
      await refreshExistingIntegration();
      renderIntegrationStatus();
      const note = document.getElementById("integration-status-message");
      note.hidden = false;
      note.textContent = "Connection saved.";
      if (window.history?.replaceState) {
        window.history.replaceState({}, "", "/ui/setup?kind=integration");
      }
      return;
    }

    if (!printerSource || !selectedPluginId) {
      showMessage("Choose a path and printer type first.", false);
      return;
    }

    const serviceInstanceId =
      printerSource === "service" ? values.service_instance_id || null : null;
    if (printerSource === "service" && !serviceInstanceId) {
      showMessage("Connect a compatible service first, or choose Standalone / LAN.", false);
      return;
    }
    if (printerSource === "service" && !config.serial) {
      showMessage("Select a printer from the connected service.", false);
      return;
    }

    const res = await fetch("/v1/printers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        plugin_id: pluginId,
        config,
        enabled: true,
        service_instance_id: serviceInstanceId,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      showMessage(body.detail || "Could not save printer.", false);
      return;
    }
    await fetch("/v1/ui/welcome/complete", { method: "POST" });
    await refreshPrinters();
    renderPrinterList();
    const note = document.getElementById("printer-list-message");
    note.hidden = false;
    note.textContent = "Printer saved.";
  } catch (err) {
    showMessage(String(err), false);
  }
});

init();
