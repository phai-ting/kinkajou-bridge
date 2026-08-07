(function () {
  const root = document.getElementById("root");
  const errorEl = document.getElementById("error");
  const nameEl = document.getElementById("name");
  const pluginEl = document.getElementById("plugin");
  const connectionEl = document.getElementById("connection");
  const stateEl = document.getElementById("print-state");
  const jobEl = document.getElementById("job");
  const fillEl = document.getElementById("fill");
  const pctEl = document.getElementById("pct");
  const layersEl = document.getElementById("layers");
  const elapsedEl = document.getElementById("elapsed");
  const remainingEl = document.getElementById("remaining");
  const totalEl = document.getElementById("total");
  const nozzleEl = document.getElementById("nozzle");
  const bedEl = document.getElementById("bed");

  function fmtTemp(value) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    return `${Number(value).toFixed(0)}°C`;
  }

  function showError(text) {
    root.hidden = true;
    errorEl.hidden = false;
    errorEl.textContent = text;
  }

  function render(update) {
    const printer = update.printer;
    const status = update.status || {};
    const job = status.job || {};
    const temps = status.temperatures || {};
    const connection = status.connection || "disconnected";
    const printState = status.print_state || "unknown";

    root.hidden = false;
    errorEl.hidden = true;

    nameEl.textContent = printer.name || "Printer";
    pluginEl.textContent = printer.plugin_id || "";
    connectionEl.className = KinkajouBridge.badgeClass(connection);
    connectionEl.textContent = connection;
    stateEl.className = `badge ${KinkajouBridge.printStateClass(printState)}`;
    stateEl.textContent = printState;
    root.dataset.state = String(printState).toLowerCase();

    jobEl.textContent = job.name || printState;

    if (job.progress == null || Number.isNaN(Number(job.progress))) {
      pctEl.textContent = "—";
      fillEl.style.width = "0%";
    } else {
      const pct = Math.max(0, Math.min(100, Number(job.progress)));
      pctEl.textContent = `${pct.toFixed(0)}%`;
      fillEl.style.width = `${pct}%`;
    }

    if (job.layer_current != null && job.layer_total != null) {
      layersEl.textContent = `Layer ${job.layer_current} / ${job.layer_total}`;
    } else if (job.layer_current != null) {
      layersEl.textContent = `Layer ${job.layer_current}`;
    } else {
      layersEl.textContent = "";
    }

    elapsedEl.textContent = KinkajouBridge.formatDuration(job.elapsed_seconds);
    remainingEl.textContent = KinkajouBridge.formatDuration(job.remaining_seconds);
    totalEl.textContent = KinkajouBridge.formatDuration(job.total_seconds);

    nozzleEl.textContent = `${fmtTemp(temps.nozzle_c)} / ${fmtTemp(temps.nozzle_target_c)}`;
    bedEl.textContent = `${fmtTemp(temps.bed_c)} / ${fmtTemp(temps.bed_target_c)}`;
  }

  KinkajouBridge.watchPrinter({
    onUpdate: render,
    onError(err) {
      showError(
        err.message && err.message.includes("No printers")
          ? err.message
          : `Cannot reach Bridge at ${KinkajouBridge.host()}. Is Bridge running? (${err.message})`
      );
    },
  });
})();
