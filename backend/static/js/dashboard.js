// 관리자 대시보드의 사용자 이용 추이와 분석 결과 분포.
(() => {
  const { segments, usageTrend } = JSON.parse(document.getElementById("chart-data").textContent);
  const canvas = document.getElementById("status-chart");
  if (!window.Chart) return void canvas.remove(); // CDN을 못 불러와도 범례에 숫자가 그대로 있음
  const usageChart = document.getElementById("usage-chart");
  usageChart.parentElement.hidden = false;
  new Chart(usageChart, {
    type: "line",
    data: {
      labels: usageTrend.map((day) => day.label),
      datasets: [
        ["used", "실제 이용", "#315d49"],
        ["visits", "접속", "#6895ad"],
        ["logins", "로그인", "#8a4fb8"],
        ["joined", "신규 가입", "#946520"],
      ].map(([key, label, color]) => ({
        label, data: usageTrend.map((day) => day[key]), borderColor: color, backgroundColor: color,
        pointRadius: 3, tension: 0, spanGaps: false,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
      plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } },
    },
  });
  document.getElementById("usage-chart-values").hidden = true;

  const empty = segments.every((s) => s.count === 0);
  new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: segments.map((s) => `${s.label} (${s.status})`),
      datasets: [{
        data: empty ? [1] : segments.map((s) => s.count),
        backgroundColor: empty ? ["#eceee8"] : segments.map((s) => s.color),
        borderColor: "#ffffff",
        borderWidth: 2,
      }],
    },
    options: {
      cutout: "68%",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { enabled: !empty, displayColors: false, callbacks: { label: (c) => `${c.label}: ${c.parsed}건` } },
      },
    },
  });
})();
