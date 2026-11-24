// 오늘 화면: 순공 시계(공부 중이면 1초마다 증가), 히어로 버튼(시작·일시정지·재개·종료), 이번 주 막대그래프.
(() => {
  const { api, errorText, hms } = window.App;
  const clock = document.getElementById("today-study");
  let seconds = Number(clock.dataset.seconds);
  clock.textContent = hms(seconds);
  if (clock.dataset.running === "1") setInterval(() => (clock.textContent = hms(++seconds)), 1000);
  const short = (s) => (s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m` : `${Math.floor(s / 60)}m`);
  document.querySelectorAll("[data-short]").forEach((n) => (n.textContent = short(Number(n.dataset.short))));

  // 히어로 버튼 → 공부 세션 API (상태가 바뀌면 화면을 다시 불러와 집계 반영)
  const hero = document.getElementById("hero");
  hero.querySelectorAll("[data-action]").forEach((button) =>
    button.addEventListener("click", async () => {
      const action = button.dataset.action;
      if (action === "end" && !confirm("공부 세션을 종료할까요?")) return;
      const url = action === "start" ? "/api/study/sessions/" : `/api/study/sessions/${hero.dataset.session}/${action}/`;
      try {
        await api(url, { method: "POST" });
        location.reload();
      } catch (x) {
        document.getElementById("hero-error").textContent = errorText(x);
      }
    })
  );
  // 이 화면이 열려 있는 동안도 연결 신호 (공부 중 탭을 이 화면에 두어도 '확인 불가'가 되지 않게)
  if (hero.dataset.status === "ACTIVE") {
    setInterval(() => document.visibilityState === "visible" && api(`/api/study/sessions/${hero.dataset.session}/heartbeat/`, { method: "POST" }).catch(() => {}), 30000);
  }

  const week = JSON.parse(document.getElementById("week-data").textContent);
  const canvas = document.getElementById("week-chart");
  if (!window.Chart) return void canvas.remove();
  new Chart(canvas, {
    type: "bar",
    data: {
      labels: week.map((d) => d.label),
      datasets: [{
        label: "순공(시간)",
        data: week.map((d) => d.hours),
        backgroundColor: week.map((d) => (d.today ? "#315d49" : "#b9cfc2")),
        borderRadius: 6,
        borderSkipped: false,
        maxBarThickness: 44,
        minBarLength: 2,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { displayColors: false, callbacks: { label: (c) => `${c.parsed.y}시간` } } },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, suggestedMax: 2, ticks: { callback: (v) => `${v}h` }, grid: { color: "#eceee8" }, border: { display: false } },
      },
    },
  });
})();
