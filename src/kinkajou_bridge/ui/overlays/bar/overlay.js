(function () {
  const root = document.getElementById("root");
  const errorEl = document.getElementById("error");
  const fillEl = document.getElementById("fill");
  const layersEl = document.getElementById("layers");
  const pctEl = document.getElementById("pct");
  const remainingEl = document.getElementById("remaining");

  function showError(text) {
    root.hidden = true;
    errorEl.hidden = false;
    errorEl.textContent = text;
  }

  function formatLayers(job) {
    const current = job.layer_current;
    const total = job.layer_total;
    if (current == null && total == null) return "—";
    if (current != null && total != null) return `Layer ${current} / ${total}`;
    if (current != null) return `Layer ${current}`;
    return `Layer — / ${total}`;
  }

  function render(update) {
    const status = update.status || {};
    const job = status.job || {};
    const printState = String(status.print_state || "unknown").toLowerCase();

    root.hidden = false;
    errorEl.hidden = true;
    root.dataset.state = printState;

    layersEl.textContent = formatLayers(job);

    if (job.progress == null || Number.isNaN(Number(job.progress))) {
      pctEl.textContent = "—";
      fillEl.style.width = "0%";
    } else {
      const pct = Math.max(0, Math.min(100, Number(job.progress)));
      pctEl.textContent = `${pct.toFixed(0)}%`;
      fillEl.style.width = `${pct}%`;
    }

    const remaining = KinkajouBridge.formatDuration(job.remaining_seconds);
    if (remaining === "—" || remaining === "0m") {
      remainingEl.textContent = remaining;
    } else {
      remainingEl.textContent = `−${remaining}`;
    }
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
