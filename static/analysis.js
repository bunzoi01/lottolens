/* Analysis page charts. Data comes from the JSON block rendered by the server. */
document.addEventListener("DOMContentLoaded", () => {
  const L = window.LottoLens;
  const D = JSON.parse(document.getElementById("analysis-data").textContent);
  const charts = [];
  let freqMode = "win";
  let hotLb = "25";

  function destroyAll() { while (charts.length) charts.pop().destroy(); }

  function drawCharts() {
    destroyAll();
    const s1 = L.css("--series-1"), s2 = L.css("--series-2"), ink2 = L.css("--ink-2");

    // Frequency: bars + flat expected line.
    const freq = freqMode === "win" ? D.freq : D.supp_freq;
    const expected = freqMode === "win" ? D.expected_freq : (D.supp_draws * 2) / 45;
    document.getElementById("freq-label").textContent =
      freqMode === "win" ? "Times drawn as a winning number" : `Times drawn as a supplementary (${D.supp_draws} draws with supps)`;
    charts.push(new Chart(document.getElementById("freq-chart"), {
      type: "bar",
      data: { labels: D.numbers, datasets: [
        L.barDataset("Times drawn", freq, s1),
        L.lineDataset("Expected", D.numbers.map(() => expected), ink2, { pointHoverRadius: 0 }),
      ] },
      options: L.baseOptions({
        plugins: { legend: { display: false }, tooltip: Object.assign(L.baseOptions().plugins.tooltip, {
          callbacks: { title: (items) => `Number ${items[0].label}`,
            label: (it) => it.datasetIndex === 0 ? ` ${it.raw} times` : ` expected ${expected.toFixed(1)}` } }) },
      }),
    }));

    // Gaps: current gap bars, average gap as dots.
    charts.push(new Chart(document.getElementById("gap-chart"), {
      type: "bar",
      data: { labels: D.numbers, datasets: [
        L.barDataset("Draws since last drawn", D.current_gap, s1),
        L.lineDataset("Average gap", D.avg_gap, s2, { showLine: false, pointRadius: 3, pointHoverRadius: 5,
          pointBorderColor: L.css("--surface"), pointBorderWidth: 1 }),
      ] },
      options: L.baseOptions({
        plugins: { legend: { display: false }, tooltip: Object.assign(L.baseOptions().plugins.tooltip, {
          callbacks: { title: (items) => `Number ${items[0].label}` } }) },
      }),
    }));

    const simpleBar = (id, labels, data, title, fmt) => charts.push(new Chart(document.getElementById(id), {
      type: "bar",
      data: { labels, datasets: [L.barDataset(title, data, s1)] },
      options: L.baseOptions({
        interaction: { mode: "nearest", intersect: false, axis: "x" },
        plugins: { legend: { display: false }, tooltip: Object.assign(L.baseOptions().plugins.tooltip, {
          callbacks: { label: (it) => " " + (fmt ? fmt(it.raw) : it.raw + " draws") } }) },
      }),
    }));
    simpleBar("sum-chart", D.sum_bins, D.sum_hist, "Draws");
    simpleBar("odd-chart", [0, 1, 2, 3, 4, 5, 6].map((k) => `${k} odd`), D.odd, "Draws");
    simpleBar("low-chart", [0, 1, 2, 3, 4, 5, 6].map((k) => `${k} low`), D.low, "Draws");
    simpleBar("decade-chart", D.decade_labels, D.decade_share.map((v) => +(v * 100).toFixed(1)), "Share",
      (v) => `${v}% of winning numbers`);
    const decadeChart = charts[charts.length - 1];
    decadeChart.options.scales.y.ticks.callback = (v) => v + "%";
    decadeChart.update();

    drawHeat();
    drawPairs();
  }

  // ------------------------------------------------------------ hot/cold grid (HTML)
  function drawHeat() {
    const grid = document.getElementById("heat-grid");
    grid.innerHTML = "";
    const z = D.hot[hotLb], counts = D.hot_counts[hotLb];
    D.numbers.forEach((n, i) => {
      const bg = L.divergent(z[i]);
      const cell = document.createElement("div");
      cell.className = "heat-cell";
      cell.style.background = bg;
      cell.style.color = L.inkFor(bg);
      cell.innerHTML = `${n}<small>${z[i] > 0 ? "+" : ""}${z[i].toFixed(1)}</small>`;
      const text = `Number ${n}: drawn ${counts[i]} times in the last ${hotLb} draws (z ${z[i].toFixed(2)})`;
      cell.setAttribute("aria-label", text);
      cell.addEventListener("mousemove", (e) => L.tip(text, e.clientX, e.clientY));
      cell.addEventListener("mouseleave", () => L.tip(null));
      grid.appendChild(cell);
    });
    document.getElementById("heat-bar").style.background =
      `linear-gradient(90deg, ${L.divergent(-2.5)}, ${L.divergent(0)}, ${L.divergent(2.5)})`;
  }

  // ------------------------------------------------------------ pair heatmap (canvas)
  function drawPairs() {
    const cv = document.getElementById("pair-canvas");
    const ctx = cv.getContext("2d");
    const size = cv.width, pad = 40, cell = (size - pad) / 45;
    ctx.clearRect(0, 0, size, size);
    ctx.fillStyle = L.css("--surface");
    ctx.fillRect(0, 0, size, size);
    const max = Math.max(1, D.pair_max);
    for (let i = 0; i < 45; i++) {
      for (let j = 0; j < 45; j++) {
        if (i === j) continue;
        ctx.fillStyle = L.sequential(D.pairs[i][j] / max);
        ctx.fillRect(pad + j * cell + 0.5, pad + i * cell + 0.5, cell - 1, cell - 1);
      }
    }
    ctx.fillStyle = L.css("--muted");
    ctx.font = "16px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (let k = 0; k < 45; k += 5) {
      ctx.fillText(k + 1, pad + k * cell + cell / 2, pad / 2);
      ctx.fillText(k + 1, pad / 2, pad + k * cell + cell / 2);
    }
    cv.onmousemove = (e) => {
      const r = cv.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * size - pad, y = ((e.clientY - r.top) / r.height) * size - pad;
      const j = Math.floor(x / cell), i = Math.floor(y / cell);
      if (i < 0 || j < 0 || i > 44 || j > 44 || i === j) return L.tip(null);
      L.tip(`${i + 1} & ${j + 1}: together in ${D.pairs[i][j]} draws`, e.clientX, e.clientY);
    };
    cv.onmouseleave = () => L.tip(null);
  }

  // ------------------------------------------------------------ controls
  const winBtn = document.getElementById("freq-win"), suppBtn = document.getElementById("freq-supp");
  function setFreq(mode) {
    freqMode = mode;
    winBtn.setAttribute("aria-pressed", mode === "win");
    suppBtn.setAttribute("aria-pressed", mode === "supp");
    winBtn.classList.toggle("primary", mode === "win");
    suppBtn.classList.toggle("primary", mode === "supp");
    drawCharts();
  }
  winBtn.addEventListener("click", () => setFreq("win"));
  suppBtn.addEventListener("click", () => setFreq("supp"));
  document.getElementById("hot-lb").addEventListener("change", (e) => { hotLb = e.target.value; drawHeat(); });
  document.addEventListener("lottolens:theme", drawCharts);
  setFreq("win");
});
