/* Static-site History page: search and page through the embedded draws. */
document.addEventListener("DOMContentLoaded", () => {
  // Each row: [iso date, draw number or null, [6 winners], [2 supps] or null]
  const ALL = JSON.parse(document.getElementById("draws-data").textContent);
  const PER_PAGE = 25;
  const rowsEl = document.getElementById("draw-rows");
  const info = document.getElementById("page-info");
  const prev = document.getElementById("page-prev"), next = document.getElementById("page-next");
  const search = document.getElementById("draw-search");
  let shown = ALL, page = 1;

  const fmt = new Intl.DateTimeFormat("en-AU", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const ball = (n, cls) => `<span class="ball sm${cls ? " " + cls : ""}">${n}</span>`;

  function filter(q) {
    const tokens = q.replace(/,/g, " ").split(/\s+/).filter(Boolean);
    if (!tokens.length) return ALL;
    return ALL.filter(([d, num, wins, supps]) => tokens.every((t) => {
      if (/^\d+$/.test(t) && +t <= 45) return wins.includes(+t) || (supps || []).includes(+t);
      return d.includes(t) || String(num) === t;
    }));
  }

  function render() {
    const pages = Math.max(1, Math.ceil(shown.length / PER_PAGE));
    page = Math.min(Math.max(1, page), pages);
    const slice = shown.slice((page - 1) * PER_PAGE, page * PER_PAGE);
    rowsEl.innerHTML = slice.length ? slice.map(([d, num, wins, supps]) => `<tr>
        <td>${fmt.format(new Date(d + "T00:00:00Z"))}</td>
        <td class="n">${num ? num.toLocaleString("en-AU") : "—"}</td>
        <td><span class="balls">${wins.map((n) => ball(n)).join("")}</span></td>
        <td>${supps ? `<span class="balls">${supps.map((n) => ball(n, "supp")).join("")}</span>` : '<span class="muted">—</span>'}</td>
      </tr>`).join("") : '<tr><td colspan="4" class="muted">No draws match.</td></tr>';
    info.textContent = `Page ${page} of ${pages} · ${shown.length} draws`;
    prev.disabled = page <= 1;
    next.disabled = page >= pages;
  }

  let timer;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { shown = filter(search.value.trim()); page = 1; render(); }, 200);
  });
  prev.addEventListener("click", () => { page--; render(); });
  next.addEventListener("click", () => { page++; render(); });
  render();
});
