/* Backtest charts. */
document.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("bt-data");
  if (!el) return;
  const L = window.LottoLens;
  const D = JSON.parse(el.textContent);
  const charts = [];

  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  function draw() {
    while (charts.length) charts.pop().destroy();
    const s1 = L.css("--series-1"), s2 = L.css("--series-2");
    const labels = D.per_draw.map((d) => d.draw_date);
    const lo = D.per_draw.map((d) => d.random_cum_p05), hi = D.per_draw.map((d) => d.random_cum_p95);
    charts.push(new Chart(document.getElementById("bt-cum"), {
      type: "line",
      data: { labels, datasets: [
        L.lineDataset("Random 5th percentile", lo, "transparent", { pointHoverRadius: 0, fill: false }),
        L.lineDataset("Random 95th percentile", hi, "transparent", { pointHoverRadius: 0, fill: "-1", backgroundColor: hexA(s2, 0.14) }),
        L.lineDataset("Random picks (average)", D.per_draw.map((d) => d.random_cum_mean), s2),
        L.lineDataset("LottoLens", D.per_draw.map((d) => d.algo_cum), s1),
      ] },
      options: L.baseOptions({
        plugins: { legend: { display: false }, tooltip: Object.assign(L.baseOptions().plugins.tooltip, {
          filter: (it) => it.datasetIndex >= 2,
          callbacks: { label: (it) => ` ${it.dataset.label}: ${(+it.raw).toFixed(it.datasetIndex === 3 ? 0 : 1)}` } }) },
        scales: Object.assign(L.baseOptions().scales, {
          x: Object.assign(L.baseOptions().scales.x, { ticks: { color: L.css("--muted"), maxTicksLimit: 8, font: { size: 11 } } }) }),
      }),
    }));

    const divs = ["1", "2", "3", "4", "5", "6"];
    charts.push(new Chart(document.getElementById("bt-div"), {
      type: "bar",
      data: { labels: divs.map((d) => "Div " + d), datasets: [
        L.barDataset("LottoLens", divs.map((d) => D.algo[d]), s1),
        L.barDataset("Random picks (average)", divs.map((d) => +D.random[d].toFixed(2)), s2),
      ] },
      options: L.baseOptions(),
    }));
  }
  document.addEventListener("lottolens:theme", draw);
  draw();
});
