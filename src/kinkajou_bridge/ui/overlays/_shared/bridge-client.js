/**
 * Minimal Bridge API helper for OBS overlays.
 * Query params: host, printer, interval, token, theme
 *
 * Prefer the browser's built-in fetch + WebSocket. This helper is intentionally
 * small so custom overlays can copy patterns or call Bridge directly.
 */
(function (global) {
  function params() {
    return new URLSearchParams(window.location.search);
  }

  /** @returns {"dark"|"light"} */
  function theme() {
    const t = (params().get("theme") || "dark").trim().toLowerCase();
    return t === "light" ? "light" : "dark";
  }

  function applyTheme() {
    document.documentElement.dataset.theme = theme();
  }

  applyTheme();

  function host() {
    const raw = (params().get("host") || "").trim();
    if (raw) return raw.replace(/\/$/, "");
    const loc = window.location;
    // Served by Bridge itself — stay same-origin (no local-network permission prompt).
    if (
      (loc.hostname === "127.0.0.1" || loc.hostname === "localhost") &&
      loc.pathname.indexOf("/bridge/") === 0
    ) {
      return loc.origin;
    }
    return "http://127.0.0.1:29067";
  }

  function intervalMs() {
    const n = Number(params().get("interval") || 2000);
    return Number.isFinite(n) && n >= 250 ? n : 2000;
  }

  function printerId() {
    return (params().get("printer") || "").trim() || null;
  }

  function authHeaders() {
    const token = (params().get("token") || "").trim();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  function eventsWsUrl() {
    const u = new URL(host());
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.pathname = "/v1/events";
    u.search = "";
    u.hash = "";
    const token = (params().get("token") || "").trim();
    if (token) u.searchParams.set("token", token);
    return u.toString();
  }

  async function fetchJson(path) {
    const res = await fetch(`${host()}${path}`, {
      headers: { Accept: "application/json", ...authHeaders() },
    });
    if (!res.ok) {
      throw new Error(`${res.status} ${res.statusText}`);
    }
    return res.json();
  }

  async function listPrinters() {
    return fetchJson("/v1/printers");
  }

  async function resolvePrinter() {
    const printers = await listPrinters();
    if (!Array.isArray(printers) || !printers.length) {
      return null;
    }
    const wanted = printerId();
    if (!wanted) return printers[0];
    return printers.find((p) => p.id === wanted) || null;
  }

  async function getStatus(id) {
    return fetchJson(`/v1/printers/${encodeURIComponent(id)}/status`);
  }

  /**
   * Fill missing elapsed / total / remaining from progress when possible.
   * Bridge plugins should send these fields; derivation is a fallback.
   */
  function normalizeJobTimes(job, opts) {
    const now = (opts && opts.now) || Date.now();
    const remainingAnchor = opts && opts.remainingAnchor;
    const elapsedAnchor = opts && opts.elapsedAnchor;
    const raw = job || {};
    let progress = raw.progress != null ? Number(raw.progress) : null;
    if (progress != null && (Number.isNaN(progress) || progress < 0)) progress = null;
    if (progress != null) progress = Math.max(0, Math.min(100, progress));

    let remaining =
      raw.remaining_seconds != null ? Number(raw.remaining_seconds) : null;
    let elapsed = raw.elapsed_seconds != null ? Number(raw.elapsed_seconds) : null;
    let total = raw.total_seconds != null ? Number(raw.total_seconds) : null;

    if (remainingAnchor && remainingAnchor.remaining != null) {
      const drift = (now - remainingAnchor.at) / 1000;
      remaining = Math.max(0, Math.round(remainingAnchor.remaining - drift));
    }
    if (elapsedAnchor && elapsedAnchor.elapsed != null) {
      const drift = (now - elapsedAnchor.at) / 1000;
      elapsed = Math.max(0, Math.round(elapsedAnchor.elapsed + drift));
    }

    if (total == null && elapsed != null && remaining != null) {
      total = elapsed + remaining;
    }
    if (
      total == null &&
      remaining != null &&
      progress != null &&
      progress > 0 &&
      progress < 100
    ) {
      total = Math.round(remaining / (1 - progress / 100));
    }
    if (elapsed == null && total != null && remaining != null) {
      elapsed = Math.max(0, total - remaining);
    }
    if (remaining == null && total != null && elapsed != null) {
      remaining = Math.max(0, total - elapsed);
    }
    if (
      progress == null &&
      total != null &&
      total > 0 &&
      elapsed != null
    ) {
      progress = Math.max(0, Math.min(100, (elapsed / total) * 100));
    }

    return {
      name: raw.name || raw.file_name || null,
      progress,
      remaining_seconds: remaining,
      elapsed_seconds: elapsed,
      total_seconds: total,
      layer_current: raw.layer_current ?? null,
      layer_total: raw.layer_total ?? null,
      file_name: raw.file_name || null,
    };
  }

  function formatDuration(seconds) {
    if (seconds == null || Number.isNaN(Number(seconds))) return "—";
    let s = Math.max(0, Math.round(Number(seconds)));
    const h = Math.floor(s / 3600);
    s %= 3600;
    const m = Math.floor(s / 60);
    const sec = s % 60;
    if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
    if (m > 0) return `${m}m ${String(sec).padStart(2, "0")}s`;
    return `${sec}s`;
  }

  function badgeClass(connection) {
    if (connection === "connected") return "badge ok";
    if (connection === "connecting") return "badge warn";
    if (connection === "error" || connection === "unreachable") return "badge bad";
    return "badge";
  }

  function printStateClass(printState) {
    const state = String(printState || "unknown").toLowerCase();
    if (state === "printing" || state === "preparing") return "state-printing";
    if (state === "paused") return "state-paused";
    if (state === "complete") return "state-complete";
    if (state === "failed" || state === "error" || state === "cancelled") {
      return "state-bad";
    }
    if (state === "idle") return "state-idle";
    return "state-unknown";
  }

  /**
   * Live printer subscription: HTTP bootstrap + WebSocket refresh triggers,
   * with local 1s countdown for remaining / elapsed between Bridge updates.
   */
  function watchPrinter(handlers) {
    const onUpdate = handlers && handlers.onUpdate;
    const onError = handlers && handlers.onError;
    let closed = false;
    let printer = null;
    let status = null;
    /** True while Bridge HTTP/WS link is usable; false when Bridge is down or reconnecting. */
    let bridgeReachable = false;
    let remainingAnchor = null;
    let elapsedAnchor = null;
    let ws = null;
    let tickTimer = null;
    let reconnectTimer = null;
    let refreshTimer = null;

    function markUnreachable() {
      bridgeReachable = false;
      emit();
    }

    function emit() {
      if (!onUpdate || !printer) return;
      const job = normalizeJobTimes(status && status.job, {
        remainingAnchor,
        elapsedAnchor,
      });
      const base = { ...(status || {}), job };
      // Don't keep advertising printer "connected" when we can't reach Bridge.
      if (!bridgeReachable) {
        base.connection = "unreachable";
      }
      onUpdate({
        printer,
        status: base,
        bridgeReachable,
      });
    }

    function setStatus(next) {
      status = next || {};
      bridgeReachable = true;
      const job = status.job || {};
      if (job.remaining_seconds != null) {
        remainingAnchor = {
          remaining: Number(job.remaining_seconds),
          at: Date.now(),
        };
      }
      if (job.elapsed_seconds != null) {
        elapsedAnchor = {
          elapsed: Number(job.elapsed_seconds),
          at: Date.now(),
        };
      }
      emit();
    }

    async function refresh() {
      if (closed) return;
      try {
        const resolved = await resolvePrinter();
        if (!resolved) {
          bridgeReachable = false;
          if (onError) {
            onError(
              new Error(
                "No printers found in Bridge. Add a printer, then refresh this source."
              )
            );
          }
          return;
        }
        printer = resolved;
        const next =
          resolved.status && resolved.status.job
            ? resolved.status
            : await getStatus(resolved.id);
        setStatus(next || {});
      } catch (err) {
        markUnreachable();
        // First load: surface the hard error. After that, keep last UI with "unreachable".
        if (!status && onError) onError(err);
      }
    }

    function scheduleRefresh() {
      if (refreshTimer != null) return;
      refreshTimer = setTimeout(() => {
        refreshTimer = null;
        refresh();
      }, 120);
    }

    function connectWs() {
      if (closed) return;
      try {
        ws = new WebSocket(eventsWsUrl());
      } catch (err) {
        markUnreachable();
        if (!status && onError) onError(err);
        reconnectTimer = setTimeout(connectWs, 2500);
        return;
      }

      ws.addEventListener("open", () => {
        // Re-sync from HTTP whenever the live link returns.
        refresh();
      });

      ws.addEventListener("message", (event) => {
        let payload = null;
        try {
          payload = JSON.parse(event.data);
        } catch {
          return;
        }
        if (!printer || !payload) return;
        if (payload.printer_id && payload.printer_id !== printer.id) return;
        const type = String(payload.type || "");
        if (
          type.startsWith("print.") ||
          type.startsWith("printer.") ||
          !type
        ) {
          scheduleRefresh();
        }
      });

      ws.addEventListener("close", () => {
        if (closed) return;
        markUnreachable();
        reconnectTimer = setTimeout(connectWs, 2500);
      });

      ws.addEventListener("error", () => {
        try {
          ws.close();
        } catch {
          /* ignore */
        }
      });
    }

    refresh();
    connectWs();
    tickTimer = setInterval(emit, 1000);

    return function stop() {
      closed = true;
      if (tickTimer != null) clearInterval(tickTimer);
      if (reconnectTimer != null) clearTimeout(reconnectTimer);
      if (refreshTimer != null) clearTimeout(refreshTimer);
      if (ws) {
        try {
          ws.close();
        } catch {
          /* ignore */
        }
      }
    };
  }

  global.KinkajouBridge = {
    host,
    intervalMs,
    printerId,
    theme,
    applyTheme,
    eventsWsUrl,
    listPrinters,
    resolvePrinter,
    getStatus,
    normalizeJobTimes,
    formatDuration,
    badgeClass,
    printStateClass,
    watchPrinter,
  };
})(window);
