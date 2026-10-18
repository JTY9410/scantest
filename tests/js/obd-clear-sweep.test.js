// node --test tests/js — 제어기 순회(기본 스캔)·고장코드 지우기(2026-10-18 대표 결정)
const test = require("node:test");
const assert = require("node:assert/strict");
const P = require("../../app/static/js/components/obd-plan.js");
const D = require("../../app/static/js/components/obd-driver.js");

function elm(Driver, answer) {
  const sent = [];
  const driver = new Driver(async (text) => {
    const command = text.replace(/\r$/, "");
    sent.push(command);
    const reply = answer(command);
    if (reply !== null) setTimeout(() => driver.feed(reply), 2);
  });
  return { driver, sent };
}

test("응답 주소가 +8이 아닌 717은 71D로 받는다", () => {
  assert.deepEqual(P.headerCommands("717", "can11"), ["ATSH717", "ATCRA71D"]);
  assert.deepEqual(P.headerCommands("7A0", "can11"), ["ATSH7A0", "ATCRA7A8"]);
});

test("제어기 순회: 응답 없는 제어기는 19 04를 건너뛴다", () => {
  const ctx = P.newContext();
  ctx.bus = "can11";
  const probe = { header: "7A3", command: "1902FF", probe: true, sweep: true, bus: "can" };
  P.observe(probe, "1902FF", "NO DATA", ctx);
  assert.match(P.skipReason({ header: "7A3", command: "1904", expand: "dtcs", bus: "can" }, ctx), /응답하지 않아/);
});

test("지우기: 차가 움직이면 14·04를 보내지 않는다", () => {
  const ctx = P.newContext();
  ctx.bus = "can11";
  P.observe({ group: "clear_check", command: "010D" }, "010D", "7E8 03 41 0D 0A", ctx);
  assert.equal(ctx.speed, 10);
  assert.match(P.skipReason({ group: "clear", header: "7E0", command: "14FFFFFF", bus: "can" }, ctx), /움직이고/);
  P.observe({ group: "clear_check", command: "010D" }, "010D", "7E8 03 41 0D 00", ctx);
  assert.equal(P.skipReason({ group: "clear", header: "7E0", command: "14FFFFFF", bus: "can" }, ctx), null);
});

test("지우기: 모든 14가 54면 04를 건너뛰고, 하나라도 실패하거나 OBD 고장코드가 있으면 04를 보낸다", () => {
  const fallback = { group: "clear", command: "04", when: { clear_fallback: true, obd_dtcs: false } };
  const ctx = P.newContext();
  ctx.bus = "can11";
  P.observe({ group: "clear", header: "7E0", command: "14FFFFFF" }, "14FFFFFF", "7E8 01 54", ctx);
  assert.match(P.skipReason(fallback, ctx), /04는 보내지 않았습니다/);
  P.observe({ group: "clear", header: "7D2", command: "14FFFFFF" }, "14FFFFFF", "7DA 03 7F 14 22", ctx);
  assert.equal(P.skipReason(fallback, ctx), null);
  const ctx2 = P.newContext();
  P.observe({ group: "clear", header: "7B2", command: "14FFFFFF" }, "14FFFFFF", null, ctx2);
  assert.equal(ctx2.clearFailed, true, "무응답도 실패로 본다");
  assert.equal(P.skipReason({ ...fallback, when: { clear_fallback: true, obd_dtcs: true } }, P.newContext()), null);
});

test("지우기: NRC 7F일 때만 10 03 → 14 → 10 01, 응답을 모두 이어 붙인다", async () => {
  const calls = [];
  const replies = { "14FFFFFF": ["7E8 03 7F 14 7F", "7E8 01 54"], 1003: ["7E8 06 50 03 00 32 01 F4"], 1001: ["7E8 06 50 01 00 32 01 F4"] };
  const request = async (s) => {
    calls.push(s.command);
    return replies[s.command].shift();
  };
  const step = { group: "clear", header: "7E0", command: "14FFFFFF", session_fallback: true };
  const reply = await D.withSessionFallback(request, step, "can11");
  assert.deepEqual(calls, ["14FFFFFF", "1003", "14FFFFFF", "1001"]);
  assert.ok(reply.includes("7E8 01 54") && reply.includes("50 03"));
});

test("지우기: NRC 22(조건 불충족)나 읽기 단계에서는 세션을 바꾸지 않는다", async () => {
  const calls = [];
  const request = async (s) => {
    calls.push(s.command);
    return "7E8 03 7F 14 22";
  };
  await D.withSessionFallback(request, { group: "clear", header: "7E0", command: "14FFFFFF", session_fallback: true }, "can11");
  await D.withSessionFallback(request, { group: "uds", header: "7E0", command: "14FFFFFF" }, "can11");
  const read = async (s) => {
    calls.push(s.command);
    return "7E8 03 7F 22 7F";
  };
  await D.withSessionFallback(read, { group: "uds", header: "7E0", command: "22B002", session_fallback: true }, "can11");
  assert.deepEqual(calls, ["14FFFFFF", "14FFFFFF", "22B002"]);
});

test("지우기: 10 03 뒤 오류가 나도 10 01은 보낸다", async () => {
  const calls = [];
  const request = async (s) => {
    calls.push(s.command);
    if (s.command === "14FFFFFF" && calls.length > 1) throw new Error("끊김");
    return s.command === "14FFFFFF" ? "7E8 03 7F 14 7F" : "7E8 02 50 03";
  };
  await assert.rejects(D.withSessionFallback(request, { group: "clear", header: "7E0", command: "14FFFFFF", session_fallback: true }, "can11"));
  assert.deepEqual(calls, ["14FFFFFF", "1003", "14FFFFFF", "1001"]);
});

test("ELM327: NRC 78은 단계의 pendingRetries(지우기 6회)만큼 다시 보낸다", async () => {
  let n = 0;
  const { driver, sent } = elm(D.ElmDriver, (c) => {
    if (c === "14FFFFFF") {
      n += 1;
      return n < 6 ? "7E8 03 7F 14 78\r\r>" : "7E8 01 54\r\r>";
    }
    return "OK\r\r>";
  });
  driver.bus = "can11";
  const reply = await driver.request({ header: "7E0", command: "14FFFFFF", timeoutMs: 50, pendingRetries: 6 });
  assert.match(reply, /54/);
  assert.equal(sent.filter((c) => c === "14FFFFFF").length, 6);
  assert.ok(sent.includes("ATSTFF") && sent.includes("ATST32"));
});

test("ELM327: 제어기 순회 단계는 ATST19로 짧게 기다리고, 끝나면 ATST32로 돌린다", async () => {
  const { driver, sent } = elm(D.ElmDriver, (c) => (c.startsWith("19") || c.startsWith("22") ? "NO DATA\r\r>" : "OK\r\r>"));
  driver.bus = "can11";
  await driver.request({ header: "7A0", command: "1902FF", timeoutMs: 1000, st: "19" });
  await driver.request({ header: "7A1", command: "1902FF", timeoutMs: 1000, st: "19" });
  await driver.request({ header: "7E4", command: "220101", timeoutMs: 3000 });
  assert.deepEqual(sent, ["ATSH7A0", "ATCRA7A8", "ATST19", "1902FF", "ATSH7A1", "ATCRA7A9", "1902FF",
    "ATSH7E4", "ATCRA7EC", "ATST32", "220101"]);
});
