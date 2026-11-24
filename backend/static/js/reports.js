// 기록 화면: 시간 표시, 오인식 정정 (PATCH /api/study/events/<id>/ {is_valid}).
(() => {
  const { api, errorText, hm } = window.App;
  document.querySelectorAll("[data-sec]").forEach((n) => (n.textContent = hm(Number(n.dataset.sec))));
  document.querySelectorAll("[data-event]").forEach((button) =>
    button.addEventListener("click", async () => {
      const valid = button.dataset.valid !== "1"; // 누르면 반대로
      try {
        await api(`/api/study/events/${button.dataset.event}/`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_valid: valid }),
        });
        button.dataset.valid = valid ? "1" : "0";
        button.textContent = valid ? "오인식으로 표시" : "정정 취소";
        button.closest("tr").classList.toggle("invalid", !valid);
      } catch (x) {
        document.getElementById("report-error").textContent = errorText(x);
      }
    })
  );
})();
