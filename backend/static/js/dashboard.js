// 관리자 대시보드: 분석 결과 분포(작업 상태별) 원형 그래프 (Chart.js). 동작별 막대와 숫자는 템플릿이 ORM 집계로 그린다.
(() => {
  const { segments } = JSON.parse(document.getElementById("chart-data").textContent);
  const canvas = document.getElementById("status-chart");
  if (!window.Chart) return void canvas.remove(); // CDN을 못 불러와도 범례에 숫자가 그대로 있음
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
