// 데이터입력분석: 차량번호로 차량정보를 조회해(차량검색과 같은 조회) 차종을 보여 준다. 차대번호는 보여 주지 않는다.
(() => {
  "use strict";

  const FIELDS = [
    ["car_no", "차량번호"], ["diag_company", "제조사"], ["diag_model", "모델"], ["diag_submodel", "세부모델"],
    ["diag_grade", "등급"], ["diag_year", "세부등급(연식)"], ["diag_registred_date", "최초등록일"],
  ];

  function mount(form) {
    const input = form.elements.car_no;
    const button = form.querySelector("[data-car-lookup]");
    const status = form.querySelector("[data-car-status]");
    const result = form.querySelector("[data-car-result]");

    function render(car) {
      result.replaceChildren(...FIELDS.flatMap(([key, label]) => {
        const dt = document.createElement("dt");
        dt.textContent = label;
        const dd = document.createElement("dd");
        const value = car[key];
        dd.textContent = value === null || value === undefined || value === "" ? "-" : String(value);
        return [dt, dd];
      }));
      result.hidden = false;
    }

    async function lookup() {
      const carNo = input.value.trim();
      if (!carNo) {
        status.textContent = "차량번호를 입력하세요.";
        input.focus();
        return;
      }
      button.disabled = true;
      result.hidden = true;
      status.textContent = "차량 정보를 조회하는 중…";
      try {
        const response = await fetch(form.dataset.lookupUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": form.elements.csrf_token.value },
          body: JSON.stringify({ carNo }),
        });
        const data = await response.json().catch(() => ({ message: "서버 응답을 읽지 못했습니다" }));
        if (!response.ok) throw new Error(`${data.message || "요청 실패"} (HTTP ${response.status})`);
        render({ ...data.car, car_no: data.car_no });
        status.textContent = data.car.diag_company && data.car.diag_model
          ? "조회했습니다. 아래에 데이터를 올리고 '올리고 추출하기'를 누르세요."
          : "제조사·모델이 없어 차종을 정할 수 없습니다. 차량번호를 확인하세요.";
      } catch (error) {
        status.textContent = `조회 실패: ${error.message}`;
      } finally {
        button.disabled = false;
      }
    }

    button.addEventListener("click", lookup);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        lookup();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-canlab-input]").forEach(mount);
  });
})();
