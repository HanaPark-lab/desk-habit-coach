// 집중 모드: 세션 버튼 → /api/study/sessions/. 카메라를 켜면 AI 착석 추정 모드(초당 6장 /frames/),
// 끄면 수동 타이머 모드. 상태·시간은 서버 응답으로 맞추고, 화면은 1초마다 그 사이만 채운다. 프레임은 저장하지 않는다.
(() => {
  const { api, errorText, pad, actionName } = window.App;
  const $ = (id) => document.getElementById(id);
  const FOCUS_GOAL = 50 * 60;   // 50분 집중 → 휴식 권장 (선택)
  const FRAME_MS = 1000 / 6;    // 6fps = 실시간 행동 모델 학습 주기 (한 번에 한 요청, 늦으면 그 프레임은 건너뜀)
  const HEARTBEAT_MS = 30000;   // 카메라를 끈 상태의 연결 신호
  const PILL = {
    AI: { STUDY: "공부 중 (AI 추정)", BREAK: "휴식 중", AWAY: "장기 자리 비움", AWAY_PENDING: "자리 비움 · 복귀 확인 중", UNKNOWN: "카메라 확인 필요" },
    MANUAL: { STUDY: "공부 중 (수동)", BREAK: "휴식 중", AWAY: "장기 자리 비움", AWAY_PENDING: "자리 비움 · 복귀 확인 중", UNKNOWN: "연결 끊김 · 확인 불가" },
  };
  const EDGES = [[0, 5], [0, 6], [5, 6], [5, 7], [7, 9], [6, 8], [8, 10], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16]];
  let session = null;
  let secs = { AUTO: 0, MANUAL: 0, BREAK: 0, AWAY: 0, AWAY_PENDING: 0, UNKNOWN: 0 }; // 서버 값 + 다음 응답까지 화면에서만 증가
  let drinks = Number($("t-drink").textContent.replace(/\D/g, "")) || 0;
  let stream = null;
  let busy = false;
  let breakAlerted = false;
  let lastSync = Date.now(); // 마지막 서버 응답 시각
  const breakOpt = $("opt-break");
  breakOpt.checked = localStorage.getItem("breakAlert") === "1";
  breakOpt.addEventListener("change", () => localStorage.setItem("breakAlert", breakOpt.checked ? "1" : "0"));

  const mmss = (sec) => `${pad(Math.floor(sec / 60))}:${pad(Math.floor(sec % 60))}`;
  const focusElapsed = () => {
    if (!(session && session.current_state === "STUDY" && session.current_started_at)) return 0;
    const until = session.mode === "AI" ? Math.min(Date.now(), lastSync + 5000) : Date.now(); // 응답이 끊기면 시계 정지
    return Math.max(0, (until - new Date(session.current_started_at)) / 1000);
  };

  function showAlert(title, text) {
    $("alert-title").textContent = title;
    $("alert-text").textContent = text;
    $("alert").hidden = false;
  }

  function render(s) {
    session = s && s.status !== "ENDED" ? s : null;
    $("btn-start").hidden = !!session;
    $("btn-pause").hidden = !session || session.status !== "ACTIVE";
    $("btn-resume").hidden = !session || session.status !== "PAUSED";
    $("btn-end").hidden = !session;
    const mode = session ? session.mode : "MANUAL";
    $("focus-pill").textContent = session ? PILL[mode][session.current_state] || session.status : s ? "세션 종료" : "대기";
    $("focus-pill").dataset.state = session ? session.current_state : "";
    $("mode-label").textContent = mode === "AI" ? "AI 착석 추정" : "수동 타이머";
    if (!s) return;
    lastSync = Date.now();
    secs = { ...s.study_seconds_by_source, BREAK: s.break_seconds, AWAY: s.away_seconds, AWAY_PENDING: s.pending_seconds, UNKNOWN: s.unknown_seconds };
    $("opt-phone").checked = !!s.phone_detection;
    $("tile-phone").hidden = !s.phone_detection;
    $("t-phone").textContent = `${s.distractions}회`;
    if (!session && stream) toggleCamera();
    paint();
  }

  const min = (sec) => `${Math.floor(sec / 60)}분`;
  // 1초마다 시계 갱신 (서버 값 + 경과 시간)
  function paint() {
    const live = session && session.current_state === "STUDY";
    const elapsed = focusElapsed();
    $("focus-clock").textContent = mmss(elapsed);
    $("focus-bar").style.width = `${Math.min(100, (elapsed / FOCUS_GOAL) * 100)}%`;
    const left = FOCUS_GOAL - elapsed;
    $("break-countdown").textContent = !breakOpt.checked ? "알림 꺼짐" : live ? (left > 0 ? mmss(left) : "지금 쉬어요") : "--:--";
    if (breakOpt.checked && live && left <= 0 && !breakAlerted) {
      breakAlerted = true;
      showAlert("50분 집중했어요. 잠깐 쉬어 갈까요?", "물 한 잔 마시고 어깨를 풀어 보세요. 일시정지를 누르면 휴식으로 기록됩니다.");
    }
    $("t-ai").textContent = min(secs.AUTO);
    $("t-manual").textContent = min(secs.MANUAL);
    $("t-other").textContent = `${Math.floor(secs.BREAK / 60)} · ${Math.floor((secs.AWAY + secs.AWAY_PENDING) / 60)} · ${min(secs.UNKNOWN)}`;
    $("t-drink").textContent = `${drinks}회`;
  }
  setInterval(() => {
    if (session) {  // 공부 시간은 STUDY일 때만 증가 (복귀 확인 중·자리 비움·확인 불가 동안 정지)
      // AI 모드에서 서버 응답이 5초 넘게 없으면 서버도 '확인 불가'로 정산하므로 공부 시간을 늘리지 않음
      const st = session.mode === "AI" && Date.now() - lastSync > 5000 ? "UNKNOWN" : session.current_state;
      if (st === "STUDY") secs[session.mode === "AI" ? "AUTO" : "MANUAL"]++;
      else if (st in secs) secs[st]++;
    }
    paint();
  }, 1000);

  async function call(path, method = "POST") {
    $("study-error").textContent = "";
    try {
      render(await api(path, { method }));
      return true;
    } catch (x) {
      $("study-error").textContent = errorText(x);
      return false;
    }
  }
  const url = (action) => `/api/study/sessions/${session.id}/${action}/`;
  $("btn-start").addEventListener("click", async ({ currentTarget: button }) => {
    button.disabled = true;
    breakAlerted = false;
    $("alert").hidden = true;
    $("study-error").textContent = "";
    try {
      render(await api("/api/study/sessions/", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: stream ? "AI" : "MANUAL" }) }));
    } catch (x) {
      if (x.status === 409) location.reload();
      else $("study-error").textContent = errorText(x);
    } finally {
      button.disabled = false;
    }
  });
  $("btn-pause").addEventListener("click", () => call(url("pause")));
  $("btn-resume").addEventListener("click", () => { breakAlerted = false; $("alert").hidden = true; call(url("resume")); });
  $("btn-end").addEventListener("click", async ({ currentTarget: button }) => {
    if (!session || !confirm("세션을 종료할까요?")) return;
    button.disabled = true;
    if (await call(url("end"))) location.replace(button.dataset.todayUrl);
    else button.disabled = false;
  });

  // ---- 카메라 + 프레임 전송 ----
  const video = $("camera");
  const overlay = $("overlay");
  const grab = document.createElement("canvas");

  // 카메라 켜기 = AI 착석 추정 모드, 끄기 = 수동 타이머 모드 (서버에 모드 전환 요청)
  const setMode = (mode, extra = {}) => session && session.status !== "ENDED" &&
    api(url("mode"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode, ...extra }) })
      .then(render).catch((x) => ($("study-error").textContent = errorText(x)));
  $("opt-phone").addEventListener("change", (e) => {
    if (session) setMode(session.mode, { phone_detection: e.target.checked });
    else e.target.checked = false;
  });
  // 페이지를 떠나면 카메라를 끈다 (서버 상태는 프레임이 끊겨 5초 뒤 '확인 불가'로 정산됨)
  window.addEventListener("pagehide", () => stream && stream.getTracks().forEach((t) => t.stop()));

  async function toggleCamera() {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
      video.hidden = $("live-badge").hidden = true;
      $("live-empty").hidden = false;
      $("btn-camera").textContent = "카메라 켜기";
      overlay.getContext("2d").clearRect(0, 0, overlay.width, overlay.height);
      await setMode("MANUAL");
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
      video.srcObject = stream;
      video.hidden = $("live-badge").hidden = false;
      $("live-empty").hidden = true;
      $("btn-camera").textContent = "카메라 끄기";
      await setMode("AI");
    } catch (x) {
      $("study-error").textContent = {
        NotAllowedError: "카메라 권한이 거부되었습니다. 주소창의 카메라 아이콘에서 허용해 주세요.",
        NotFoundError: "연결된 카메라를 찾을 수 없습니다.",
        NotReadableError: "다른 프로그램이 카메라를 쓰고 있습니다.",
      }[x && x.name] || "카메라를 사용할 수 없습니다. 브라우저 권한을 확인해 주세요. (localhost 또는 https에서만 동작)";
    }
  }
  $("btn-camera").addEventListener("click", toggleCamera);

  function draw(persons, phones) {
    const w = (overlay.width = video.clientWidth);
    const h = (overlay.height = video.clientHeight);
    const g = overlay.getContext("2d");
    g.clearRect(0, 0, w, h);
    g.lineWidth = 3;
    g.font = "15px system-ui, sans-serif";
    for (const p of persons) {
      const [x1, y1, x2, y2] = p.box;
      g.strokeStyle = "#a6e3a1";
      g.setLineDash([8, 6]);
      g.strokeRect(x1 * w, y1 * h, (x2 - x1) * w, (y2 - y1) * h);
      g.setLineDash([]);
      g.fillStyle = "#a6e3a1";
      g.fillRect(x1 * w, y1 * h - 24, 110, 24);
      g.fillStyle = "#16301f";
      g.fillText(`사람 ${p.index}`, x1 * w + 6, y1 * h - 7);
      const k = p.keypoints;
      g.strokeStyle = "#c7f59a";
      for (const [a, b] of EDGES) {
        if (k[a][2] < 0.3 || k[b][2] < 0.3) continue;
        g.beginPath();
        g.moveTo(k[a][0] * w, k[a][1] * h);
        g.lineTo(k[b][0] * w, k[b][1] * h);
        g.stroke();
      }
      g.fillStyle = "#c7f59a";
      for (const [x, y, c] of k) if (c >= 0.3) g.beginPath(), g.arc(x * w, y * h, 4, 0, Math.PI * 2), g.fill();
    }
    for (const ph of phones) {
      const [x1, y1, x2, y2] = ph.box;
      g.strokeStyle = "#f28b82";
      g.strokeRect(x1 * w, y1 * h, (x2 - x1) * w, (y2 - y1) * h);
      g.fillStyle = "#f28b82";
      g.fillText("휴대폰", x1 * w + 4, y1 * h - 6);
    }
  }

  async function sendFrame() {
    if (!stream || !session || session.mode !== "AI" || session.status !== "ACTIVE" || busy || video.readyState < 2) return;
    busy = true; // 한 번에 한 요청만
    const sentFor = session.id;
    try {
      grab.width = 640;
      grab.height = Math.round((640 * video.videoHeight) / video.videoWidth) || 480;
      grab.getContext("2d").drawImage(video, 0, 0, grab.width, grab.height);
      const blob = await new Promise((r) => grab.toBlob(r, "image/jpeg", 0.7));
      const form = new FormData();
      form.append("frame", blob, "frame.jpg");
      form.append("seq", String(Date.now())); // 증가하는 프레임 번호 (새로고침해도 줄지 않음)
      const data = await api(url("frames"), { method: "POST", body: form });
      if (data.ignored || !session || session.id !== sentFor || !stream) return; // 늦은 응답이 바뀐 세션을 덮지 않게
      render(data);
      draw(data.persons, data.phones);
      $("live-status").textContent = { present: "", absent: "· 자리에 사람이 보이지 않아요", unclear: "· 확인 어려움 (가림·여러 명·흐림)" }[data.observation] ?? "";
      if (data.recorded_event === "DRINK") drinks++; // 서버에 저장된 경우에만 횟수 증가
      if (data.recorded_event) {
        let label = "drink_return";
        if (data.recorded_event === "MOVEMENT") {
          // Match the server's display label within the movement group, including ties.
          const score = (name) => data.action_candidates.find(({ label }) => label === name)?.probability ?? 0;
          label = score("walk_turn_walk") > score("wave") ? "walk_turn_walk" : "wave";
        }
        const detail = label === "walk_turn_walk"
          ? "휴식 시간은 카메라의 이탈·복귀 시각으로 따로 판단해요."
          : "잘못 인식된 행동은 기록 화면에서 정정할 수 있어요.";
        showAlert(`${actionName(label)} · 1회 기록`, detail);
      }
      if (data.phone_alert) showAlert("잠깐, 다시 집중해 볼까요?", "휴대폰 사용으로 추정되는 행동이 일정 시간 지속되었어요.");
    } catch (x) {
      $("live-status").textContent = `· ${errorText(x, "분석 서버 연결 실패")}`;
    } finally {
      busy = false;
    }
  }
  setInterval(sendFrame, FRAME_MS);

  // 카메라가 꺼져 있을 때만 연결 신호 (켜져 있으면 프레임이 신호 역할). AI 모드에서는 공부 시간을 복구하지 않음
  setInterval(() => {
    if (session && !stream && document.visibilityState === "visible") call(url("heartbeat"));
  }, HEARTBEAT_MS);

  const openId = JSON.parse($("open-session").textContent);
  if (openId) {
    // 새로고침하면 카메라가 꺼진 상태 → AI 모드였으면 수동 모드로 맞춤 (꺼진 카메라로 착석을 추정하지 않음)
    call(`/api/study/sessions/${openId}/heartbeat/`).then(() => session && session.mode === "AI" && !stream && setMode("MANUAL"));
  } else render(null);
})();
