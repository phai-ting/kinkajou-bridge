(function () {
  const root = document.getElementById("root");
  const errorEl = document.getElementById("error");
  const nameEl = document.getElementById("name");
  const pctEl = document.getElementById("pct");
  const jobEl = document.getElementById("job");
  const fillEl = document.getElementById("fill");
  const etaEl = document.getElementById("eta");

  function showError(text) {
    root.hidden = true;
    errorEl.hidden = false;
    errorEl.textContent = text;
  }

  function fmtEta(seconds) {
    if (seconds == null || Number.isNaN(Number(seconds))) return "—";
    const mins = Math.max(0, Math.round(Number(seconds) / 60));
    if (mins < 60) return `~${mins} min left`;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return `~${h}h ${m}m left`;
  }

  async function tick() {
    try {
      const printer = await KinkajouBridge.resolvePrinter();
      if (!printer) {
        showError("No printers found in Bridge. Add a printer, then refresh this source.");
        return;
      }
      const status = printer.status || (await KinkajouBridge.getStatus(printer.id)) || {};
      const job = status.job || {};
      const progress = job.progress != null ? Number(job.progress) : null;

      root.hidden = false;
      errorEl.hidden = true;
      nameEl.textContent = printer.name || "Printer";
      jobEl.textContent = job.name || status.print_state || "Idle";
      if (progress == null || Number.isNaN(progress)) {
        pctEl.textContent = "—";
        fillEl.style.width = "0%";
      } else {
        const pct = Math.max(0, Math.min(100, progress));
        pctEl.textContent = `${pct.toFixed(0)}%`;
        fillEl.style.width = `${pct}%`;
      }
      etaEl.textContent = fmtEta(job.remaining_seconds);
    } catch (err) {
      showError(
        `Cannot reach Bridge at ${KinkajouBridge.host()}. Is Bridge running? (${err.message})`
      );
    }
  }

  tick();
  setInterval(tick, KinkajouBridge.intervalMs());
})();
