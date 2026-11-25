// 오늘 화면의 공부 시간, 집중 모드 진입, 주간 그래프.
(() => {
  const { api, errorText, formatTimes, hm } = window.App;
  const clock = document.getElementById("today-study");
  const goal = document.getElementById("today-goal");
  const goalSeconds = Number(goal.dataset.goalSeconds);
  const goalText = document.getElementById("today-goal-pct");
  const initialSeconds = Number(clock.dataset.seconds);
  const loadedAt = Date.now();
  if (clock.dataset.running === "1") {
    setInterval(() => {
      const seconds = initialSeconds + Math.floor((Date.now() - loadedAt) / 1000);
      clock.textContent = hms(seconds);
      const percent = goalSeconds > 0 ? Math.min(100, Math.round(seconds / goalSeconds * 100)) : 0;
      goalText.textContent = percent;
      goal.setAttribute("aria-valuenow", percent);
      goal.firstElementChild.style.width = `${percent}%`;
    }, 1000);
  }

  const start = document.getElementById("today-start");
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) location.reload();
  });
  start?.addEventListener("click", async () => {
    const error = document.getElementById("hero-error");
    start.disabled = true;
    error.textContent = "";
    try {
      await api(start.dataset.createUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "MANUAL" }),
      });
    } catch (x) {
      // 다른 탭에서 먼저 세션을 만들었다면 집중 모드가 열린 세션을 불러온다.
      if (x.status !== 409) {
        error.textContent = errorText(x);
        start.disabled = false;
        return;
      }
    }
    location.assign(start.dataset.studyUrl);
  });

  const hero = document.getElementById("hero");
  if (hero.dataset.status === "ACTIVE") {
    setInterval(() => {
      if (document.visibilityState === "visible") {
        api(`/api/study/sessions/${hero.dataset.session}/heartbeat/`, { method: "POST" }).catch(() => {});
      }
    }, 30000);
  }

  const canvas = document.getElementById("week-chart");
  if (!canvas) return;

  function drawWeek() {
    const week = JSON.parse(document.getElementById("week-data").textContent);
    canvas.parentElement.hidden = false;
    new window.Chart(canvas, {
      type: "bar",
      data: {
        labels: week.map((day) => day.label),
        datasets: [{
          label: "공부 시간",
          data: week.map((day) => day.seconds),
          backgroundColor: week.map((day) => day.today ? "#315d49" : "#b9cfc2"),
          borderRadius: 6,
          borderSkipped: false,
          maxBarThickness: 44,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: { displayColors: false, callbacks: { label: ({ parsed }) => formatTime(parsed.y) } },
        },
        scales: {
          x: { grid: { display: false } },
          y: { beginAtZero: true, ticks: { callback: formatTime }, grid: { color: "#eceee8" }, border: { display: false } },
        },
      },
    });
    document.getElementById("week-values").hidden = true;
  }

  if (window.Chart) drawWeek();
  else document.getElementById("today-chart-library").addEventListener("load", drawWeek, { once: true });
})();
