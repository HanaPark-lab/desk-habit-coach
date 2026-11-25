// 모든 화면 공통: API 호출(CSRF 포함), DOM 생성, 시간 표시. 사용자 데이터는 textContent로만 넣는다.
window.App = (() => {
  const actionNames = JSON.parse(document.getElementById("action-display-names").textContent);
  const actionName = (label) => Object.hasOwn(actionNames, label) ? actionNames[label] : label;
  const csrf = (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || "";

  async function api(url, options = {}) {
    const res = await fetch(url, {
      credentials: "same-origin",
      ...options,
      headers: { "X-CSRFToken": csrf, Accept: "application/json", ...(options.headers || {}) },
    });
    const body = res.status === 204 ? null : await res.json().catch(() => null);
    if (!res.ok) throw Object.assign(new Error(`HTTP ${res.status}`), { status: res.status, body });
    return body;
  }

  const errorText = (x, fallback) =>
    x && x.body ? Object.values(x.body).flat().join(" ") : fallback || "요청에 실패했습니다. 잠시 후 다시 시도해 주세요.";

  function el(tag, props = {}, ...kids) {
    const node = document.createElement(tag);
    Object.assign(node, props);
    node.append(...kids.filter((k) => k != null));
    return node;
  }

  const pad = (n) => String(n).padStart(2, "0");
  const hms = (sec) => `${pad(Math.floor(sec / 3600))}:${pad(Math.floor((sec % 3600) / 60))}:${pad(Math.floor(sec % 60))}`;
  const hm = (sec) => `${Math.floor(sec / 3600)}시간 ${Math.floor((sec % 3600) / 60)}분`;
  const formatTime = (seconds) => seconds < 60 ? `${seconds}초` : hm(seconds);

  return { api, errorText, el, hms, formatTime, pad, actionName };
})();
