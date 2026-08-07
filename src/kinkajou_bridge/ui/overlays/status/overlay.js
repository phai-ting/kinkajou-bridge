(function () {
  const root = document.getElementById("root");
  const errorEl = document.getElementById("error");
  const nameEl = document.getElementById("name");
  const pluginEl = document.getElementById("plugin");
  const connectionEl = document.getElementById("connection");
  const stateEl = document.getElementById("print-state");
  const messageEl = document.getElementById("message");

  function badgeClass(connection) {
    if (connection === "connected") return "badge ok";
    if (connection === "connecting") return "badge warn";
    if (connection === "error") return "badge bad";
    return "badge";
  }

  function showError(text) {
    root.hidden = true;
    errorEl.hidden = false;
    errorEl.textContent = text;
  }

  async function tick() {
    try {
      const printer = await KinkajouBridge.resolvePrinter();
      if (!printer) {
        showError("No printers found in Bridge. Add a printer, then refresh this source.");
        return;
      }
      const status = printer.status || (await KinkajouBridge.getStatus(printer.id)) || {};
      root.hidden = false;
      errorEl.hidden = true;
      nameEl.textContent = printer.name || "Printer";
      pluginEl.textContent = printer.plugin_id || "";
      const connection = status.connection || "disconnected";
      connectionEl.className = badgeClass(connection);
      connectionEl.textContent = connection;
      stateEl.textContent = status.print_state || "unknown";
      if (status.message) {
        messageEl.hidden = false;
        messageEl.textContent = status.message;
      } else {
        messageEl.hidden = true;
        messageEl.textContent = "";
      }
    } catch (err) {
      showError(
        `Cannot reach Bridge at ${KinkajouBridge.host()}. Is Bridge running? (${err.message})`
      );
    }
  }

  tick();
  setInterval(tick, KinkajouBridge.intervalMs());
})();
