// 대시보드 블루투스 카드: 진단기 연결 상태, 빠른 점검(저장 없이 해석), 결과지로 저장.
(() => {
  "use strict";

  const config = window.WecarObd?.readConfig();
  const root = document.getElementById("obd-quick");
  if (!config || !root) return;
  const link = window.WecarObd.bindPanel(root.querySelector("[data-obd-panel]"), config);

  const form = root.querySelector("[data-quick-form]");
  const runBtn = root.querySelector("[data-quick-run]");
  const saveBtn = root.querySelector("[data-quick-save]");
  const status = root.querySelector("[data-quick-status]");
  const result = root.querySelector("[data-quick-result]");
  const CAPTURE_LIMIT_MS = 60000;

  let lines = [];
  let running = false;

  const canRun = () => link.ready && config.requests.length > 0 && !running;
  link.addEventListener("status", () => {
    runBtn.disabled = !canRun();
  });

  function vehicle() {
    return form.elements.vehicle.value.trim() || `빠른 점검 ${link.info.name || ""}`.trim();
  }

  function formData(fields) {
    const body = new FormData();
    body.append("csrf_token", form.elements.csrf_token.value);
    Object.entries(fields).forEach(([key, value]) => body.append(key, value));
    return body;
  }

  async function post(url, fields) {
    const response = await fetch(url, { method: "POST", body: formData(fields), credentials: "same-origin" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || `HTTP ${response.status}`);
    return data;
  }

  function formatValue({ value, unit }) {
    const text = Number(value).toLocaleString("ko-KR", { maximumFractionDigits: 2 });
    if (!unit) return text;
    return unit === "%" || unit === "°C" ? `${text}${unit}` : `${text} ${unit}`;
  }

  function render(data) {
    root.querySelector("[data-quick-vin]").textContent = data.vin || "-";
    root.querySelector("[data-quick-ecus]").textContent =
      data.ecus.map((e) => `${e.request_id} ${e.label}`).join(", ") || "-";
    const dtcs = Object.values(data.dtcs).flat();
    root.querySelector("[data-quick-dtcs]").textContent = dtcs.length
      ? dtcs.map((d) => (d.desc ? `${d.code} ${d.desc}` : d.code)).join(", ")
      : data.dtcCheckedEcus.length ? `없음 (${data.dtcCheckedEcus.length}개 ECU 조회)` : "조회하지 못함";
    const body = root.querySelector("[data-quick-values]");
    body.replaceChildren(...data.values.map((v) => {
      const row = document.createElement("tr");
      const label = document.createElement("td");
      label.className = "font-semibold";
      label.setAttribute("data-primary", "");
      label.textContent = v.label;
      const value = document.createElement("td");
      value.className = "num";
      value.setAttribute("data-label", "값");
      value.textContent = formatValue(v);
      row.append(label, value);
      return row;
    }));
    result.hidden = false;
  }

  async function run() {
    running = true;
    runBtn.disabled = true;
    saveBtn.disabled = true;
    result.hidden = true;
    status.textContent = "차량에서 값을 읽는 중…";
    const deadline = Date.now() + CAPTURE_LIMIT_MS;
    try {
      lines = await window.WecarObd.capture(link, config.requests, {
        vehicle: vehicle(),
        stop: () => Date.now() > deadline,
      });
      if (!lines.some((line) => line.includes(" RX "))) throw new Error("응답을 받지 못했습니다. 시동과 진단기를 확인하세요.");
      status.textContent = "해석 중…";
      const data = await post(config.previewUrl, { content: `${lines.join("\n")}\n` });
      render(data);
      status.textContent = data.values.length
        ? `값 ${data.values.length}개를 읽었습니다.`
        : "응답은 받았지만 적용 중인 해석 규칙과 맞는 값이 없습니다.";
      saveBtn.disabled = false;
    } catch (error) {
      status.textContent = `점검 실패: ${error.message}`;
    } finally {
      running = false;
      runBtn.disabled = !canRun();
    }
  }

  async function save() {
    saveBtn.disabled = true;
    status.textContent = "결과지로 저장하는 중…";
    try {
      const data = await post(config.saveUrl, {
        vehicle: vehicle(),
        filename: `quick-${new Date().toISOString().replace(/[:.]/g, "-")}.txt`,
        content: `${lines.join("\n")}\n`,
        report: "1",
      });
      status.textContent = "저장했습니다. ";
      const anchor = document.createElement("a");
      anchor.href = data.report_url;
      anchor.className = "underline";
      anchor.textContent = "결과지 보기";
      status.append(anchor);
    } catch (error) {
      status.textContent = `저장 실패: ${error.message}`;
      saveBtn.disabled = false;
    }
  }

  runBtn.addEventListener("click", run);
  saveBtn.addEventListener("click", save);
})();
