// 분석 화면 공통: 작업 등록(POST) → 작업 ID로 2초마다 상태 조회 → 사람별 결과 표시.
// - /analyses/ (교과 사용자 분석 화면): 같은 화면에서 상태·결과 표시 (?job=<id> 로 새로고침해도 유지)
// - /analyses/new/ : 등록 후 상세 화면으로 이동
// - /analyses/<id>/: 상태·결과 + 제목·메모 수정·삭제
// 기록 여부(record)는 서버가 판정한 값을 그대로 보여 준다.
(() => {
  const { api, errorText, el } = window.App;
  const $ = (id) => document.getElementById(id);
  const ACTIONS = { drink_return: "물 마시기", wave: "손 흔들기", walk_turn_walk: "걷기", other: "기타 동작" };
  const STATUS = { PENDING: "대기", STARTED: "처리 중", SUCCESS: "완료", FAILURE: "실패" };
  const POLL_MS = 2000;
  const inputName = (t) => (t === "IPCAM" ? "IP Webcam" : "영상 업로드");
  const inline = !!$("result") && !$("job-detail"); // 교과 분석 화면
  let pollTimer = null;
  let afterDone = null; // 분석 완료·실패 후 할 일 (IP Webcam 미리보기 다시 켜기)

  function renderJob(job) {
    const done = job.status === "SUCCESS" || job.status === "FAILURE";
    const current = done ? 2 : job.status === "STARTED" ? 1 : 0;
    document.querySelectorAll("#steps li").forEach((li, i) => {
      li.className = i < current ? "done" : i > current ? "" : job.status === "FAILURE" ? "fail" : done ? "done" : "now";
      if (li.dataset.step === "STARTED") li.textContent = job.input_type === "IPCAM" ? "영상 수집·AI 분석" : "AI 분석 중";
      if (li.dataset.step === "DONE") li.textContent = job.status === "FAILURE" ? "실패" : "완료";
      li.toggleAttribute("aria-current", i === current);
    });
    const parts = [`작업 ${String(job.id).slice(0, 8)}`, STATUS[job.status], inputName(job.input_type)];
    if (job.processing_ms != null) parts.push(`처리 ${(job.processing_ms / 1000).toFixed(1)}초`);
    $("status-text").textContent = parts.join(" · ");

    const box = $("result");
    if (!done) return void box.replaceChildren(el("p", { className: "muted", textContent: "결과를 기다리는 중…" }));
    const nodes = [];
    if (job.predictions.length) {
      const head = el("tr", {}, ...["Track ID", "예측 동작", "신뢰도", "Window"].map((t) => el("th", { scope: "col", textContent: t })));
      const rows = job.predictions.map((p) =>
        el("tr", {},
          el("td", { textContent: String(p.track_id) }),
          el("td", {}, el("strong", { textContent: ACTIONS[p.action_label] || p.action_label }), el("br"), el("small", { className: "muted", textContent: p.action_label })),
          el("td", { textContent: p.confidence.toFixed(2) }),
          el("td", { textContent: String(p.window_count) })
        )
      );
      nodes.push(el("table", { className: "result-table" }, el("thead", {}, head), el("tbody", {}, ...rows)));
    }
    const r = job.record;
    const kind = r.recorded ? "ok" : job.status === "FAILURE" ? "fail" : "ng";
    const label = { ok: "기록됨", ng: "기록 안 함", fail: "실패" }[kind];
    nodes.push(el("p", { className: `verdict ${kind}`, textContent: `${label} · ${r.reason}` }));
    box.replaceChildren(...nodes);
  }

  function track(id) {
    clearTimeout(pollTimer);
    if (inline) history.replaceState(null, "", `?job=${encodeURIComponent(id)}`);
    poll(id);
  }

  async function poll(id) {
    try {
      const job = await api(`/api/analyses/${encodeURIComponent(id)}/status/`);
      renderJob(job);
      if (job.status === "PENDING" || job.status === "STARTED") {
        pollTimer = setTimeout(() => poll(id), POLL_MS);
        return;
      }
      if (afterDone) afterDone();
      if (inline && !document.querySelector(`[data-job-row="${CSS.escape(String(id))}"]`)) {
        location.replace(`/analyses/?job=${encodeURIComponent(id)}`); // 최근 이력 표에 새 작업 반영
      }
    } catch (x) {
      $("status-text").textContent = x.status === 404 ? "작업을 찾을 수 없습니다." : "상태를 불러오지 못했습니다. 다시 시도하는 중…";
      if (x.status !== 404) pollTimer = setTimeout(() => poll(id), POLL_MS * 2);
    }
  }

  // ---- 분석 요청 (교과 화면·새 분석 화면) ----
  const form = $("analyze-form");
  if (form) {
    const cfg = JSON.parse($("page-config").textContent);
    let mode = "UPLOAD";
    let busy = false;
    const cameraSelect = form.elements.camera_key;
    if (cfg.cameras.length) cfg.cameras.forEach((c) => cameraSelect.append(el("option", { value: c, textContent: c })));
    else cameraSelect.append(el("option", { value: "", textContent: "허용된 카메라 없음 (.env 설정 필요)" }));

    // IP Webcam 실시간 미리보기: Django가 중계하는 MJPEG (카메라 주소는 브라우저에 보내지 않음)
    const preview = $("cam-preview");
    const previewMsg = (text) => preview && ($("cam-preview-msg").textContent = text);
    const stopPreview = (text) => {
      if (!preview) return;
      preview.removeAttribute("src"); // 연결을 끊어 카메라를 놓아줌 (DroidCam은 1곳만 접속 가능)
      preview.hidden = true;
      previewMsg(text);
    };
    const startPreview = () => {
      if (!preview || mode !== "IPCAM" || !cameraSelect.value) return;
      preview.src = `/analyses/cameras/${encodeURIComponent(cameraSelect.value)}/stream/?t=${Date.now()}`;
      preview.hidden = false;
      previewMsg("● LIVE · 실시간 미리보기");
    };
    if (preview) {
      preview.addEventListener("error", () =>
        stopPreview("카메라 화면을 불러오지 못했습니다. 앱 실행 여부, 같은 Wi-Fi인지, 다른 곳에서 보고 있지 않은지 확인하세요."));
      cameraSelect.addEventListener("change", startPreview);
      afterDone = () => (preview.hidden ? startPreview() : previewMsg("● LIVE · 실시간 미리보기"));
    }

    document.querySelectorAll("[data-mode]").forEach((tab) =>
      tab.addEventListener("click", () => {
        mode = tab.dataset.mode;
        document.querySelectorAll("[data-mode]").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
        $("upload-fields").hidden = mode !== "UPLOAD";
        $("ipcam-fields").hidden = mode !== "IPCAM";
        $("form-error").textContent = "";
        if (mode === "IPCAM") startPreview();
        else stopPreview("카메라를 고르면 실시간 화면이 나옵니다.");
      })
    );
    // 드래그 앤 드롭: 투명한 파일 입력이 영역 전체를 덮고 있어 놓기·클릭 모두 브라우저 기본 동작으로 처리
    const dz = $("dropzone");
    const dzDefault = $("dz-text").textContent;
    const showFile = () => {
      const f = form.elements.video_file.files[0];
      $("dz-text").textContent = f ? `선택됨: ${f.name} (${(f.size / 1048576).toFixed(1)}MB) · 바꾸려면 다시 놓거나 클릭` : dzDefault;
      dz.classList.toggle("has-file", !!f);
    };
    form.elements.video_file.addEventListener("change", showFile);
    ["dragenter", "dragover"].forEach((t) => dz.addEventListener(t, () => dz.classList.add("over")));
    ["dragleave", "drop"].forEach((t) => dz.addEventListener(t, () => dz.classList.remove("over")));
    const reset = () => { form.reset(); form.elements.capture_seconds.value = cfg.default_seconds; showFile(); };
    reset();
    form.addEventListener("input", () => ($("form-error").textContent = ""));

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (busy) return;
      const error = $("form-error");
      const data = new FormData();
      data.append("input_type", mode);
      data.append("title", form.elements.job_title.value.trim());
      if (mode === "UPLOAD") {
        const file = form.elements.video_file.files[0];
        if (!file) return void (error.textContent = "영상 파일을 선택해 주세요.");
        data.append("video_file", file);
      } else {
        const seconds = Number(form.elements.capture_seconds.value);
        if (!cameraSelect.value) return void (error.textContent = "사용할 카메라가 없습니다. .env의 CAMERA_..._URL을 설정해 주세요.");
        if (!(seconds >= 5 && seconds <= 15)) return void (error.textContent = "수집 시간은 5~15초로 입력해 주세요.");
        data.append("camera_key", cameraSelect.value);
        data.append("capture_seconds", String(seconds));
      }
      busy = true;
      const button = form.querySelector("[type=submit]");
      const text = button.textContent;
      button.textContent = "요청 중…";
      button.setAttribute("aria-busy", "true");
      if (mode === "IPCAM") {
        // 미리보기는 그대로 두고(서버 중계 허브를 함께 씀) 안내만 바꾼다
        if (preview && preview.hidden) startPreview();
        previewMsg(`● REC · 서버가 ${data.get("capture_seconds")}초 동안 영상을 모읍니다. 지금 동작하세요!`);
      }
      try {
        const job = await api("/api/analyses/", { method: "POST", body: data }); // 202 + 작업 ID 즉시
        if (!inline) return void (location.href = `/analyses/${job.id}/`);
        reset();
        renderJob(job);
        track(job.id);
      } catch (x) {
        error.textContent = errorText(x);
      } finally {
        busy = false;
        button.textContent = text;
        button.removeAttribute("aria-busy");
      }
    });
  }
  if (inline) {
    const jobInUrl = new URLSearchParams(location.search).get("job");
    if (jobInUrl) track(jobInUrl);
  }

  // ---- 상세 화면 ----
  const detail = $("job-detail");
  if (!detail) return;
  const id = detail.dataset.jobId;
  poll(id);
  $("edit-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target.elements;
    try {
      await api(`/api/analyses/${id}/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: f.title.value.trim(), memo: f.memo.value }),
      });
      $("edit-msg").textContent = "저장했습니다.";
    } catch (x) {
      $("edit-msg").textContent = errorText(x);
    }
  });
  $("btn-delete").addEventListener("click", async () => {
    if (!confirm("이 분석 작업과 결과, 행동 기록을 삭제할까요? 되돌릴 수 없습니다.")) return;
    try {
      await api(`/api/analyses/${id}/`, { method: "DELETE" });
      location.href = "/analyses/";
    } catch (x) {
      $("edit-msg").textContent = errorText(x);
    }
  });
})();
