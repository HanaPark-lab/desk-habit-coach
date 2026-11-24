// 기록 대시보드의 차트와 오인식 정정.
(() => {
  const { api, errorText, hm, actionName } = window.App;
  const { buckets, totals, drinkGoal } = JSON.parse(document.getElementById("report-chart-data").textContent);
  const labels = buckets.map((bucket) => bucket.label);
  const timeSeries = [
    ["auto", "AI 추정 공부", "#315d49"],
    ["manual", "수동 기록 공부", "#83a990"],
    ["break", "휴식", "#d7bb85"],
    ["away", "자리 비움", "#9b8fc4"],
    ["unknown", "확인 불가", "#c9ccc4"],
  ];

  function draw(id, config) {
    const canvas = document.getElementById(id);
    if (!canvas || !window.Chart) return;
    const plot = canvas.parentElement;
    plot.hidden = false;
    new window.Chart(canvas, config);
    plot.nextElementSibling.hidden = true;
  }

  function bars(id, datasets, { stacked = false, duration = false } = {}) {
    draw(id, {
      type: "bar",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          x: { stacked, grid: { display: false } },
          y: {
            stacked,
            beginAtZero: true,
            title: { display: !duration, text: "횟수" },
            ticks: duration ? { callback: formatTime } : { precision: 0 },
          },
        },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 12 } },
          tooltip: { callbacks: { label: (item) => `${item.dataset.label}: ${duration ? formatTime(item.raw) : `${item.raw}회`}` } },
        },
      },
    });
  }

  function formatTime(seconds) {
    return seconds < 60 ? `${seconds}초` : hm(seconds);
  }

  const series = (key, label, color) => ({ label, data: buckets.map((bucket) => bucket[key]), backgroundColor: color });
  bars("time-trend", timeSeries.map(([key, label, color]) => series(key, label, color)), { stacked: true, duration: true });

  const timeTotal = timeSeries.reduce((sum, [key]) => sum + totals[key], 0);
  draw("time-share", {
    type: "doughnut",
    data: {
      labels: timeSeries.map(([key, label]) => `${label} ${(totals[key] / (timeTotal || 1) * 100).toFixed(1)}%`),
      datasets: [{
        data: timeSeries.map(([key]) => totals[key]),
        backgroundColor: timeSeries.map(([, , color]) => color),
      }],
    },
    options: {
      cutout: "65%",
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 12 } },
        tooltip: { callbacks: { label: (item) => `${item.label} · ${formatTime(item.raw)}` } },
      },
    },
  });

  bars("drink-trend", [
    series("drink", "음료 섭취", "#6895ad"),
    {
      type: "line", label: "목표", data: labels.map(() => drinkGoal), order: -1,
      borderColor: "#315d49", borderDash: [6, 4], pointRadius: 0,
    },
  ]);
  bars("movement-trend", [
    series("wave", actionName("wave"), "#315d49"),
    series("walk", actionName("walk_turn_walk"), "#9b8fc4"),
  ]);

  const error = document.getElementById("report-error");
  document.querySelectorAll("[data-event]").forEach((button) =>
    button.addEventListener("click", async () => {
      button.disabled = true;
      error.textContent = "";
      try {
        await api(`/api/study/events/${button.dataset.event}/`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_valid: button.dataset.valid !== "1" }),
        });
        location.reload(); // 같은 조회 기간에서 정정된 ORM 집계와 행동 목록을 다시 표시한다.
      } catch (x) {
        error.textContent = errorText(x);
        button.disabled = false;
      }
    })
  );
})();
