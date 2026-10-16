/* LottoLens front end: theme toggle, clipboard, chart helpers. */
(function () {
  "use strict";

  // ---------------------------------------------------------------- theme
  function currentTheme() {
    const set = document.documentElement.dataset.theme;
    if (set) return set;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("theme-toggle");
    if (btn) btn.addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("lottolens-theme", next); } catch (e) {}
      document.dispatchEvent(new CustomEvent("lottolens:theme"));
    });
  });

  // ---------------------------------------------------------------- clipboard
  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-copy-target]");
    if (!btn) return;
    const el = document.querySelector(btn.dataset.copyTarget);
    if (!el) return;
    const text = el.dataset.copyText || el.innerText;
    try {
      await navigator.clipboard.writeText(text);
      const old = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(() => (btn.textContent = old), 1500);
    } catch (e) {
      btn.textContent = "Copy failed";
    }
  });

  // ---------------------------------------------------------------- chart helpers
  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function baseOptions(extra) {
    const grid = css("--grid"), muted = css("--muted"), ink2 = css("--ink-2");
    return Object.assign({
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: css("--ink"), titleColor: css("--surface"), bodyColor: css("--surface"),
          padding: 8, cornerRadius: 6, displayColors: true, boxPadding: 4 },
      },
      scales: {
        x: { grid: { display: false }, border: { color: css("--axis") }, ticks: { color: muted, font: { size: 11 } } },
        y: { grid: { color: grid }, border: { display: false }, ticks: { color: muted, font: { size: 11 }, precision: 0 },
          title: { display: false, color: ink2 } },
      },
    }, extra || {});
  }

  function barDataset(label, data, color, extra) {
    return Object.assign({
      label, data, backgroundColor: color, borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "start",
      maxBarThickness: 24, categoryPercentage: 0.85, barPercentage: 0.9,
    }, extra || {});
  }

  function lineDataset(label, data, color, extra) {
    return Object.assign({
      type: "line", label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0,
      pointHoverRadius: 4, tension: 0, borderJoinStyle: "round", borderCapStyle: "round",
    }, extra || {});
  }

  // Divergent colour for z-scores: blue (cold) - grey (0) - red (hot), clamped at |z| = 2.5.
  function mix(a, b, t) {
    const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
    const ch = (s) => [(s >> 16) & 255, (s >> 8) & 255, s & 255];
    const ca = ch(pa), cb = ch(pb);
    const c = ca.map((v, i) => Math.round(v + (cb[i] - v) * t));
    return `rgb(${c[0]},${c[1]},${c[2]})`;
  }
  function divergent(z) {
    const t = Math.max(-1, Math.min(1, z / 2.5));
    return t < 0 ? mix(css("--div-mid"), css("--div-neg"), -t) : mix(css("--div-mid"), css("--div-pos"), t);
  }
  function sequential(t) {
    return mix(css("--seq-lo"), css("--seq-hi"), Math.max(0, Math.min(1, t)));
  }
  function inkFor(rgb) {
    const m = rgb.match(/\d+/g).map(Number);
    const lum = (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255;
    return lum > 0.55 ? "#0b0b0b" : "#ffffff";
  }

  // A single floating tooltip shared by the HTML heat grid and the pair canvas.
  let tipEl = null;
  function tip(text, x, y) {
    if (!tipEl) { tipEl = document.createElement("div"); tipEl.className = "tip"; document.body.appendChild(tipEl); }
    if (text == null) { tipEl.style.display = "none"; return; }
    tipEl.textContent = text;
    tipEl.style.display = "block";
    tipEl.style.left = Math.min(x + 12, window.innerWidth - tipEl.offsetWidth - 8) + "px";
    tipEl.style.top = (y + 12) + "px";
  }

  window.LottoLens = { css, baseOptions, barDataset, lineDataset, divergent, sequential, inkFor, tip };
})();
