// 고장코드 지우기 흐름: 확인 창 → 계획 발급 → 진단기 실행 → 결과 저장 → 전후 비교 표시.
(() => {
  "use strict";

  const P = window.WecarObdPlan;
  if (!P) {
    console.warn("WecarObdPlan not loaded");
    return;
  }

  const clearBtn = document.querySelector("[data-clear-dtc]");
  const dialog = document.querySelector("[data-clear-dialog]");
  const resultDialog = document.querySelector("[data-clear-result]");
  if (!clearBtn || !dialog || !resultDialog) return;

  const scanId = clearBtn.dataset.clearDtc;
  const form = dialog.querySelector("[data-clear-form]");
  const status = dialog.querySelector("[data-clear-status]");
  const submit = dialog.querySelector("[data-clear-submit]");
  const targetCount = dialog.querySelector("[data-target-count]");
  const estimateTime = dialog.querySelector("[data-estimate-time]");
  const resultContent = resultDialog.querySelector("[data-result-content]");

  let link = null;
  let plan = null;
  let running = false;

  clearBtn.addEventListener("click", async () => {
    // 진단기 연결 확인
    link = window.WecarObd?.connection;
    if (!link || !link.ready) {
      alert("진단기가 연결되지 않았습니다. 스캔하기 화면에서 먼저 연결하세요.");
      return;
    }

    // 계획 발급 (예상 대상 수)
    status.textContent = "계획을 가져오는 중...";
    status.className = "flash flash-info";
    status.hidden = false;

    try {
      const response = await fetch(`/admin/scan/${scanId}/clear-plan`, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": form.elements.csrf_token.value,
        },
        body: JSON.stringify({
          carNo: form.elements.carNo.placeholder,
          conditions: false, // 아직 확인 안 함
        }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({ message: "요청 실패" }));
        throw new Error(data.message || `HTTP ${response.status}`);
      }

      plan = await response.json();
      const targets = plan.targets?.length || 0;
      targetCount.textContent = `${targets}개 제어기`;
      const seconds = Math.ceil(targets * 1.5);
      estimateTime.textContent = `약 ${seconds}초 (최대 ${Math.ceil(targets * 30 / 60)}분)`;
      status.hidden = true;

      dialog.showModal();
    } catch (error) {
      status.textContent = error.message;
      status.className = "flash flash-error";
      status.hidden = false;
      setTimeout(() => {
        status.hidden = true;
      }, 5000);
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (running) return;
    running = true;
    submit.disabled = true;

    status.textContent = "계획을 발급받는 중...";
    status.className = "flash flash-info";
    status.hidden = false;

    try {
      // 계획 재발급 (이번에는 조건 체크)
      const response = await fetch(`/admin/scan/${scanId}/clear-plan`, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": form.elements.csrf_token.value,
        },
        body: JSON.stringify({
          carNo: form.elements.carNo.value,
          conditions: form.elements.conditions.checked,
        }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({ message: "요청 실패" }));
        throw new Error(data.message || `HTTP ${response.status}`);
      }

      plan = await response.json();

      // 진단기로 실행
      status.textContent = "제어기 지우는 중...";
      const steps = plan.steps || [];
      const results = [];
      let cleared = 0;
      let total = steps.filter((s) => s.group === "clear").length;

      for (let i = 0; i < steps.length; i++) {
        const step = steps[i];
        const result = await P.request(link, step);
        results.push(result);

        if (step.group === "clear") {
          cleared++;
          status.textContent = `제어기 ${cleared}/${total} 지우는 중...`;
        }
      }

      status.textContent = "결과를 저장하는 중...";

      // 결과 저장
      const saveResponse = await fetch(`/admin/scan/${scanId}/clear`, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": form.elements.csrf_token.value,
        },
        body: JSON.stringify({
          token: plan.token,
          steps: results,
        }),
      });

      if (!saveResponse.ok) {
        const data = await saveResponse.json().catch(() => ({ message: "저장 실패" }));
        throw new Error(data.message || `HTTP ${saveResponse.status}`);
      }

      const result = await saveResponse.json();
      dialog.close();
      showResult(result);
    } catch (error) {
      status.textContent = error.message;
      status.className = "flash flash-error";
    } finally {
      running = false;
      submit.disabled = false;
    }
  });

  // form의 실제 ID 설정
  form.id = "clear-form-target";
  submit.setAttribute("form", "clear-form-target");

  function showResult(data) {
    const r = data.result || {};
    const html = `
      <div class="flash ${r.status === "ok" ? "flash-success" : r.status === "partial" ? "flash-warning" : "flash-error"}">
        <span aria-hidden="true" class="font-bold">${r.status === "ok" ? "✓" : "!"}</span>
        <p>${
          r.status === "ok"
            ? "고장코드를 모두 지웠습니다."
            : r.status === "partial"
            ? "일부 제어기에서 지우지 못했습니다."
            : "고장코드를 지우지 못했습니다."
        }</p>
      </div>

      <div class="mt-4 grid gap-4">
        <div class="grid grid-cols-3 gap-3">
          <div class="card card-body">
            <p class="text-sm font-medium text-muted">지운 코드</p>
            <p class="mt-2 text-xl font-bold text-success">${r.cleared?.length || 0}개</p>
          </div>
          <div class="card card-body">
            <p class="text-sm font-medium text-muted">남은 코드</p>
            <p class="mt-2 text-xl font-bold ${r.remaining?.length ? "text-danger" : "text-success"}">${r.remaining?.length || 0}개</p>
          </div>
          <div class="card card-body">
            <p class="text-sm font-medium text-muted">새 코드</p>
            <p class="mt-2 text-xl font-bold ${r.new?.length ? "text-warning" : "text-success"}">${r.new?.length || 0}개</p>
          </div>
        </div>

        ${r.remaining?.length ? `
          <div class="flash flash-warning">
            <span aria-hidden="true" class="font-bold">!</span>
            <p>남은 고장코드는 현재 고장(원인 미해결) 또는 영구 고장코드일 수 있습니다. 원인을 해결한 후 다시 시도하거나, 일정 주행 후 자동으로 사라질 수 있습니다.</p>
          </div>
        ` : ""}

        ${
          r.ecus?.length
            ? `
          <details class="card overflow-hidden">
            <summary class="card-body cursor-pointer font-bold">제어기별 상세 ${r.ecus.length}곳</summary>
            <table class="rtable">
              <thead>
                <tr>
                  <th scope="col">제어기</th>
                  <th scope="col">상태</th>
                  <th scope="col">세션</th>
                </tr>
              </thead>
              <tbody>
                ${r.ecus
                  .map(
                    (ecu) => `
                  <tr>
                    <td data-primary class="mono font-semibold">${ecu.address}</td>
                    <td data-label="상태">${
                      ecu.status === "cleared"
                        ? '<span class="badge badge-success">지움</span>'
                        : ecu.status === "rejected"
                        ? `<span class="badge badge-danger">거부 (NRC ${ecu.nrc || "?"})</span>`
                        : ecu.status === "pending"
                        ? '<span class="badge badge-warning">응답 대기</span>'
                        : ecu.status === "no_response"
                        ? '<span class="badge badge-">응답 없음</span>'
                        : '<span class="badge badge-">건너뜀</span>'
                    }</td>
                    <td data-label="세션">${ecu.session_used ? "확장 세션 사용 (10 03)" : "-"}</td>
                  </tr>
                `
                  )
                  .join("")}
              </tbody>
            </table>
          </details>
        `
            : ""
        }
      </div>

      <p class="mt-4 text-sm text-muted">지우기 전 스캔 결과는 이 페이지에 그대로 남아 있습니다. 현재 상태를 확인하려면 다시 스캔하세요.</p>
    `;

    resultContent.innerHTML = html;
    resultDialog.showModal();
  }

  // 대화상자 닫기 버튼
  document.querySelectorAll("[data-dialog-close]").forEach((btn) => {
    btn.addEventListener("click", () => {
      dialog.close();
      resultDialog.close();
    });
  });
})();
