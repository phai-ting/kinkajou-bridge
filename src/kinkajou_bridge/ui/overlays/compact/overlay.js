(function () {
  const root = document.getElementById("root");
  const errorEl = document.getElementById("error");
  const nameEl = document.getElementById("name");
  const stateEl = document.getElementById("print-state");
  const jobEl = document.getElementById("job");
  const fillEl = document.getElementById("fill");
  const pctEl = document.getElementById("pct");
  const timesEl = document.getElementById("times");

  function showError(text) {
    root.hidden = true;
    errorEl.hidden = false;
    errorEl.textContent = text;
  }

  function render(update) {
    const printer = update.printer;
    const status = update.status || {};
    const job = status.job || {};
    const printState = String(status.print_state || "unknown").toLowerCase();

    root.hidden = false;
    errorEl.hidden = true;
    root.dataset.state = printState;

    nameEl.textContent = printer.name || "Printer";
    stateEl.className = `badge ${KinkajouBridge.printStateClass(printState)}`;
    stateEl.textContent = printState;

    const jobName = String(job.name || "").trim();
    if (jobName) {
      jobEl.hidden = false;
      jobEl.textContent = jobName;
    } else {
      jobEl.hidden = true;
      jobEl.textContent = "";
    }

    if (job.progress == null || Number.isNaN(Number(job.progress))) {
      pctEl.textContent = "—";
      fillEl.style.width = "0%";
    } else {
      const pct = Math.max(0, Math.min(100, Number(job.progress)));
      pctEl.textContent = `${pct.toFixed(0)}%`;
      fillEl.style.width = `${pct}%`;
    }

    const remaining = KinkajouBridge.formatDuration(job.remaining_seconds);
    timesEl.textContent = remaining === "—" ? "—" : `−${remaining}`;
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
