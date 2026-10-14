// node --test tests/js
const test = require("node:test");
const assert = require("node:assert/strict");
const D = require("../../app/static/js/components/obd-driver.js");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// 가짜 ELM 진단기: answer(command)가 돌려준 글자를 비동기로 보낸다(null이면 답하지 않음).
function elm(Driver, answer) {
  const sent = [];
  const driver = new Driver(async (text) => {
    const command = text.replace(/\r$/, "");
    sent.push(command);
    const reply = answer(command);
    if (reply !== null) setTimeout(() => driver.feed(reply), 5);
  });
  return { driver, sent };
}

test("ELM327: 초기화는 프로필 형식을 덮지 않고, 답이 없으면 실패", async () => {
  const { driver, sent } = elm(D.ElmDriver, (c) => (c === "ATZ" ? "ELM327 v1.5\r\r>" : "OK\r\r>"));
  await driver.init({ protocol: "ATSPA6" });
  assert.deepEqual(sent, ["ATZ", "ATE0", "ATL0", "ATSPA6", "ATH1", "ATS1", "ATCAF1", "ATAT1"]);
  sent.length = 0;
  await driver.init({ init: ["ATZ", "ATE0", "ATS0"] });
  assert.deepEqual(sent, ["ATZ", "ATE0", "ATS0", "ATH1", "ATCAF1", "ATAT1"], "프로필의 ATS0 뒤에 ATS1을 보내지 않는다");
  const other = elm(D.ElmDriver, () => "?\r\r>").driver;
  await assert.rejects(other.init(), /답하지 않습니다/);
});

test("ELM327: 시간 초과 뒤 늦게 온 응답은 다음 명령 응답으로 읽지 않는다", async () => {
  let first = true;
  const sent = [];
  const driver = new D.ElmDriver(async (text) => {
    sent.push(text.trim());
    if (first) {
      first = false;
      setTimeout(() => driver.feed("7E8 03 41 0D 00\r\r>"), 80);
    } else {
      setTimeout(() => driver.feed("7E8 04 41 0C 1A F8\r\r>"), 5);
    }
  });
  assert.equal(await driver.send("010D", 30), "");
  assert.equal(await driver.send("010C", 500), "7E8 04 41 0C 1A F8\r\r");
});

test("ELM327: 연결이 끊기면 기다리던 명령이 바로 실패한다", async () => {
  const { driver } = elm(D.ElmDriver, () => null);
  const pending = driver.send("0100", 30000);
  await sleep(10);
  driver.fail(new Error("진단기 연결이 끊겼습니다."));
  await assert.rejects(pending, /끊겼습니다/);
  await assert.rejects(driver.send("0100"), /끊겼습니다/);
});

test("ELM327: 주소 설정·수신 필터·응답 대기(NRC 78) 복구", async () => {
  let tries = 0;
  const { driver, sent } = elm(D.ElmDriver, (c) => {
    if (c === "22F190") {
      tries += 1;
      return tries < 2 ? "7E8 03 7F 22 78\r\r>" : "7E8 10 14 62 F1 90 4B 4D 48\r\r>";
    }
    if (c === "ATDPN") return "A6\r\r>";
    return "OK\r\r>";
  });
  await driver.request({ command: "ATDPN" });
  assert.equal(driver.bus, "can11");
  const reply = await driver.request({ header: "7E0", command: "22F190", timeoutMs: 100 });
  assert.match(reply, /62 F1 90/);
  assert.deepEqual(sent.slice(1), ["ATSH7E0", "ATCRA7E8", "22F190", "ATSTFF", "22F190", "ATST32"]);
  sent.length = 0;
  await driver.request({ command: "0101" });
  assert.deepEqual(sent, ["ATSH7DF", "ATCRA", "0101"], "주소를 바꾼 뒤 기능 주소 요청은 필터를 푼다");
});

test("STN: STPX로 주소·데이터를 한 번에 보내고, 모르면 ELM 방식으로 돌아간다", async () => {
  const { driver, sent } = elm(D.StnDriver, (c) => (c.startsWith("STPX") ? "7E8 03 41 0D 20\r\r>" : "OK\r\r>"));
  driver.bus = "can11";
  assert.match(await driver.request({ header: "7E0", command: "010D", timeoutMs: 1000 }), /41 0D 20/);
  assert.deepEqual(sent, ["ATCRA7E8", "STPX h:7E0, d:010D, t:1000"]);
  sent.length = 0;
  await driver.request({ command: "03" });
  assert.deepEqual(sent, ["ATCRA", "03"]);

  const old = elm(D.StnDriver, (c) => (c.startsWith("STPX") ? "?\r\r>" : c === "010D" ? "7E8 03 41 0D 20\r\r>" : "OK\r\r>"));
  old.driver.bus = "can11";
  assert.match(await old.driver.request({ header: "7E0", command: "010D" }), /41 0D 20/);
  assert.equal(old.driver.stpx, false);
  assert.ok(old.sent.includes("ATSH7E0"));
});

test("slcan: 프레임 변환과 ISO-TP 나누기", () => {
  assert.deepEqual(D.parseSlcan("t7E88064100983B8013001A2B"), { id: "7E8", data: [6, 0x41, 0, 0x98, 0x3b, 0x80, 0x13, 0] });
  assert.deepEqual(D.parseSlcan("T18DAF1108034100BE00000000"), { id: "18DAF110", data: [3, 0x41, 0, 0xbe, 0, 0, 0, 0] });
  assert.equal(D.parseSlcan("z"), null);
  assert.equal(D.slcanFrame("7DF", [2, 1, 0, 0, 0, 0, 0, 0]), "t7DF80201000000000000");
  assert.deepEqual(D.segment([0x22, 0xf1, 0x90]), [[3, 0x22, 0xf1, 0x90, 0, 0, 0, 0]]);
  const long = D.segment([0x19, 0x04, 1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(long[0], [0x10, 10, 0x19, 0x04, 1, 2, 3, 4]);
  assert.deepEqual(long[1], [0x21, 5, 6, 7, 8, 0, 0, 0]);
  assert.ok(D.answers("7DF", "7EC") && !D.answers("7DF", "7CE"));
  assert.ok(D.answers("7C6", "7CE") && D.answers("18DA10F1", "18DAF110") && D.answers("18DB33F1", "18DAF118"));
  assert.equal(D.requestIdFor("7E8"), "7E0");
  assert.equal(D.requestIdFor("18DAF110"), "18DA10F1");
});

// 가짜 slcan 어댑터. car(id, data)가 [[지연 ms, 프레임 줄], ...]을 돌려준다.
function slcan(car) {
  const sent = [];
  const driver = new D.SlcanDriver(async (text) => {
    for (const line of text.split("\r").filter(Boolean)) {
      sent.push(line);
      const frame = D.parseSlcan(line);
      if (!frame) {
        setTimeout(() => driver.feed(line === "V" ? "V1013\r" : "\r"), 2);
        continue;
      }
      setTimeout(() => driver.feed("z\r"), 1);
      for (const [delay, reply] of car(frame.id, frame.data, driver)) setTimeout(() => driver.feed(`${reply}\r`), delay);
    }
  });
  return { driver, sent };
}

test("slcan: CAN 속도·주소 길이를 찾고 여러 프레임 응답에 흐름 제어를 보낸다", async () => {
  const { driver, sent } = slcan((id, data, drv) => {
    if (drv.bitrate !== 500000 || id.length !== 8) return [];
    if (id === "18DB33F1" && data[1] === 0x01) return [[5, "T18DAF1108064100983B801300"]];
    if (id === "18DA10F1" && data[1] === 0x09) return [[5, "T18DAF11081014490201585858"]];
    if (id === "18DA10F1" && data[0] === 0x30) {
      return [[3, "T18DAF11082130303030303030"], [6, "T18DAF1108223030303030303000"]];
    }
    return [];
  });
  await driver.init();
  assert.equal(driver.version, "V1013");
  const support = await driver.request({ command: "0100", timeoutMs: 500 });
  assert.equal(driver.bus, "can29");
  assert.match(support, /^18DAF110 06 41 00 98 3B 80 13 00$/);
  assert.equal(await driver.request({ command: "ATDPN" }), "A7");
  assert.equal(driver.supports("ATRV"), false);
  const vin = await driver.request({ header: "18DA10F1", command: "0902", timeoutMs: 500 });
  assert.equal(vin.split("\r").length, 3);
  assert.ok(sent.includes(D.slcanFrame("18DA10F1", [0x30, 0, 0, 0, 0, 0, 0, 0])), "첫 프레임을 받으면 흐름 제어를 보낸다");
});

test("slcan: 응답 대기(NRC 78) 뒤 최종 응답까지 기다린다", async () => {
  const { driver } = slcan((id, data) => {
    if (id === "7DF") return [[5, "t7E88064100983B801300"]];
    if (id === "7E4" && data[1] === 0x22) return [[5, "t7EC8037F227800000000"], [120, "t7EC80562010100FF0000"]];
    return [];
  });
  await driver.init({ bitrate: 500000 });
  const reply = await driver.request({ header: "7E4", command: "220101", timeoutMs: 80 });
  assert.match(reply, /7F 22 78/);
  assert.match(reply, /62 01 01/);
});

test("identify: ELM·STN·slcan을 가린다", async () => {
  const run = async (answer) => {
    let listener = () => {};
    const write = async (text) => {
      const reply = answer(text.trim());
      if (reply !== null) setTimeout(() => listener(reply), 5);
    };
    return D.identify(write, (fn) => {
      listener = fn;
      return () => {};
    });
  };
  assert.equal(await run((c) => (c === "ATI" ? "ELM327 v1.5\r\r>" : "?\r\r>")), "elm327");
  assert.equal(await run((c) => (c === "ATI" ? "ELM327 v1.4b\r\r>" : "STN2120 r4.3.2\r\r>")), "stn");
  assert.equal(await run((c) => (c === "V" ? "V1013\r" : "\x07")), "slcan");
  assert.equal(await run(() => null), null);
});
