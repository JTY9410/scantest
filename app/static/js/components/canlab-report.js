// 위스캔 결과지 그래프. 데이터는 #report-data JSON, 색은 tokens.css 변수에서 읽는다.
(() => {
  "use strict";

  document.querySelectorAll("[data-print]").forEach((button) =>
    button.addEventListener("click", () => window.print()),
  );

  const source = document.getElementById("report-data");
  if (!source || !window.Chart) return;
  const data = JSON.parse(source.textContent);
  const css = getComputedStyle(document.documentElement);
  const token = (name) => css.getPropertyValue(`--wc-color-${name}`).trim();
  const color = {
    ink: token("ink"),
    info: token("info"),
    success: token("success"),
    warning: token("warning"),
    danger: token("danger"),
    line: token("border"),
    muted: token("text-muted"),
    track: token("surface-2"),
  };

  Chart.defaults.font.family = css.getPropertyValue("--wc-font-sans").trim();
  Chart.defaults.color = color.muted;
  Chart.defaults.borderColor = color.line;
  Chart.defaults.maintainAspectRatio = false;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) Chart.defaults.animation = false;

  function draw(id, config) {
    const canvas = document.getElementById(id);
    if (canvas) new Chart(canvas, config);
  }

  function gauge(id, value, tone) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    if (value === null || value === undefined) {
      canvas.closest("figure").querySelector("figcaption").textContent += " — 값 없음";
      return;
    }
    const shown = Math.max(0, Math.min(100, value));
    new Chart(canvas, {
      type: "doughnut",
      data: { datasets: [{ data: [shown, 100 - shown], backgroundColor: [tone, color.track], borderWidth: 0 }] },
      options: {
        rotation: -90,
        circumference: 180,
        cutout: "72%",
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
      },
      plugins: [{
        id: "gaugeLabel",
        afterDraw(chart) {
          const { ctx, chartArea } = chart;
          ctx.save();
          ctx.fillStyle = color.ink;
          ctx.font = `700 1.5rem ${Chart.defaults.font.family}`;
          ctx.textAlign = "center";
          ctx.fillText(`${value}%`, (chartArea.left + chartArea.right) / 2, chartArea.bottom - 8);
          ctx.restore();
        },
      }],
    });
  }

  gauge("chart-soc", data.soc, data.soc !== null && data.soc < 20 ? color.warning : color.info);
  gauge("chart-soh", data.soh, data.soh !== null && data.soh < 70 ? color.danger : color.success);

  const bar = (rows, unit, tone, extra = {}) => ({
    type: "bar",
    data: {
      labels: rows.map((r) => r.label),
      datasets: [{ label: unit, data: rows.map((r) => r.value), backgroundColor: tone, borderRadius: 6 }],
    },
    options: { plugins: { legend: { display: false } }, scales: { y: { title: { display: true, text: unit } } }, ...extra },
  });

  if (data.temps.length) draw("chart-temps", bar(data.temps, "°C", color.warning));
  if (data.cells.length) {
    const values = data.cells.map((c) => c.value);
    const pad = 0.05;
    draw("chart-cells", bar(data.cells, "V", color.info, {
      scales: { y: { min: Math.min(...values) - pad, max: Math.max(...values) + pad, title: { display: true, text: "V" } } },
    }));
  }

  const series = data.series || {};
  const voltage = series.pack_voltage;
  const current = series.pack_current;
  if (voltage || current) {
    const first = (voltage || current).points[0]?.[0] || 0;
    const line = (s, tone, axis) => ({
      label: `${s.label}(${s.unit})`,
      data: s.points.map(([t, v]) => ({ x: (t - first) / 1000, y: v })),
      borderColor: tone,
      backgroundColor: tone,
      pointRadius: 0,
      yAxisID: axis,
    });
    draw("chart-series", {
      type: "line",
      data: { datasets: [voltage && line(voltage, color.ink, "y"), current && line(current, color.info, "y1")].filter(Boolean) },
      options: {
        parsing: false,
        scales: {
          x: { type: "linear", title: { display: true, text: "경과 시간(초)" } },
          y: { display: Boolean(voltage), position: "left", title: { display: true, text: "V" } },
          y1: { display: Boolean(current), position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "A" } },
        },
      },
    });
  } else {
    document.querySelector('[data-chart-optional="series"]')?.remove();
  }

  // 로그 눈금이라 0 이하 값(방전 전류 등)은 비교 그래프에서 뺀다. 표에는 모두 있다.
  const compare = data.compare.filter((c) => c.truth > 0 && c.decoded > 0);
  if (compare.length) {
    draw("chart-compare", {
      type: "bar",
      data: {
        labels: compare.map((c) => c.label),
        datasets: [
          { label: "G스캔 정답", data: compare.map((c) => c.truth), backgroundColor: color.muted, borderRadius: 4 },
          { label: "위스캔 해석", data: compare.map((c) => c.decoded), backgroundColor: color.ink, borderRadius: 4 },
        ],
      },
      options: { scales: { y: { type: "logarithmic", title: { display: true, text: "값(로그 눈금)" } } } },
    });
  }
})();
