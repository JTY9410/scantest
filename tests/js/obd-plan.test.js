// node --test tests/js
const test = require("node:test");
const assert = require("node:assert/strict");
const P = require("../../app/static/js/components/obd-plan.js");

test("frames: 11비트·29비트·공백 없는 응답·K-Line", () => {
  assert.deepEqual(P.frames("7E8 06 41 00 98 3B 80 13", "can11")[0].source, "7E8");
  assert.equal(P.frames("18 DA F1 10 03 41 0D 20", "can29")[0].source, "18DAF110");
  assert.deepEqual(P.frames("7E8064100983B8013", "can11")[0].data, [6, 0x41, 0, 0x98, 0x3b, 0x80, 0x13]);
  const kline = P.frames("48 6B 10 41 0C 1A F8 C5", "serial")[0];
  assert.equal(kline.source, "10");
  assert.deepEqual(kline.data, [0x41, 0x0c, 0x1a, 0xf8]);
});

test("messages: ISO-TP 여러 프레임을 ECU별로 합친다", () => {
  const reply = "7E8 10 0B 59 02 FF 01 33 00\r7E9 03 41 05 50\r7E8 21 09 C1 23 00 08 AA AA\r>";
  const found = P.messages(reply, "can11");
  assert.deepEqual(found.get("7E8")[0], [0x59, 0x02, 0xff, 0x01, 0x33, 0x00, 0x09, 0xc1, 0x23, 0x00, 0x08]);
  assert.deepEqual(P.confirmedDtcs(reply, "can11"), ["013300", "C12300"]);
  assert.deepEqual(P.confirmedDtcs("7E8 07 59 02 FF 01 33 00 04", "can11"), [], "대기(bit2)만이면 제외");
  assert.deepEqual(found.get("7E9")[0], [0x41, 0x05, 0x50]);
});

test("bitmap·고장코드 수", () => {
  const support = P.bitmap("7E8 06 41 00 98 3B 80 13\r7E9 06 41 00 80 00 00 01", "can11", 0x01, 0);
  assert.ok(support.has(0x01) && support.has(0x0c) && support.has(0x20));
  assert.ok(!support.has(0x02));
  assert.ok(P.bitmap("7E8 07 42 00 00 40 00 00 00", "can11", 0x02, 0).has(0x02));
  assert.equal(P.dtcCount("7E8 06 41 01 82 07 65 21\r7E9 06 41 01 01 00 00 00", "can11"), 3);
  assert.equal(P.dtcCount("NO DATA", "can11"), null);
});

test("recovery: 오류별 복구 방법", () => {
  assert.equal(P.recovery("STOPPED\r\r", "can11", "010C"), "stopped");
  assert.equal(P.recovery("BUFFER FULL", "can11", "220101"), "buffer");
  assert.equal(P.recovery("CAN ERROR", "can11", "0100"), "bus");
  assert.equal(P.recovery("7EC 03 7F 22 78\r", "can11", "220101"), "pending");
  assert.equal(P.recovery("7EC 03 7F 22 78\r7EC 03 7F 22 31\r", "can11", "220101"), null);
  assert.equal(P.recovery("7E8 04 41 0C 1A F8", "can11", "010C"), null);
  assert.equal(P.recovery("DATA ERROR", "can11", "0902"), "buffer");
  assert.equal(P.recovery("7E8 03 7F 19 21\r", "can11", "1902FF"), "busy");
  assert.equal(P.recovery("7E8 03 7F 19 21\r7E9 03 59 02 FF\r", "can11", "1902FF"), null);
});

test("skipReason: when 조건과 버스", () => {
  const ctx = P.newContext();
  assert.equal(P.skipReason({ command: "0120", when: { pid: "20" } }, ctx), null, "비트맵을 모르면 보낸다");
  P.observe({}, "ATDPN", "A6", ctx);
  P.observe({}, "0100", "7E8 06 41 00 98 3B 80 12", ctx);
  assert.match(P.skipReason({ command: "0120", when: { pid: "20" } }, ctx), /지원하지 않는/);
  assert.equal(P.skipReason({ command: "010C", when: { pid: "0C" } }, ctx), null);
  assert.equal(P.skipReason({ command: "020C00", when: { dtc: true, pid02: "0C" } }, ctx), null, "02 비트맵이 없으면 01로 판단");
  P.observe({}, "0101", "7E8 06 41 01 00 07 65 00", ctx);
  assert.match(P.skipReason({ command: "020200", when: { dtc: true } }, ctx), /고장코드가 없어/);

  const can29 = P.newContext();
  P.observe({}, "ATDPN", "A7", can29);
  assert.match(P.skipReason({ header: "7E2", command: "1902FF", bus: "can" }, can29), /29비트/);
  assert.equal(P.headerFor({ header: "7E0", header29: "18DA10F1" }, can29), "18DA10F1");

  const serial = P.newContext();
  P.observe({}, "ATDPN", "A3", serial);
  assert.match(P.skipReason({ command: "190209", bus: "can" }, serial), /K-Line/);
});

test("requests: PID 묶음·MID·19 04 펼치기", () => {
  const ctx = P.newContext();
  P.observe({}, "ATDPN", "A6", ctx);
  P.observe({}, "0100", "7E8 06 41 00 BE 3F A8 13", ctx);
  const pids = P.requests({ command: "01", label: "실시간", expand: "pids", pids: ["04", "05", "0C", "0D", "0F", "11", "1C", "2F"] }, ctx);
  assert.deepEqual(pids.items.map((i) => i.command), ["0104050C0D0F11", "011C"]);

  const serial = P.newContext();
  P.observe({}, "ATDPN", "A3", serial);
  assert.equal(P.requests({ command: "01", label: "x", expand: "pids", pids: ["0C", "0D"] }, serial).items.length, 2);

  assert.equal(P.requests({ command: "06", label: "m", expand: "mids" }, ctx).items.length, 0);
  P.observe({}, "0600", "7E8 06 46 00 C0 00 00 01", ctx);
  assert.deepEqual(P.requests({ command: "06", label: "m", expand: "mids" }, ctx).items.map((i) => i.command),
    ["0601", "0602"]);

  const uds = { header: "7E0", header29: "18DA10F1", command: "1902FF" };
  P.observe(uds, "1902FF", "7E8 10 0F 59 02 FF 01 33 00\r7E8 21 09 C1 23 00 08 02 11\r7E8 22 00 08 AA AA AA AA AA", ctx);
  const snap = P.requests({ ...uds, command: "1904", label: "s", expand: "dtcs", limit: 2 }, ctx);
  assert.deepEqual(snap.items.map((i) => i.command), ["1904013300FF", "1904C12300FF"]);
});

test("headerCommands: 요청 주소와 수신 필터", () => {
  assert.deepEqual(P.headerCommands("7E0", "can11"), ["ATSH7E0", "ATCRA7E8"]);
  assert.deepEqual(P.headerCommands("7DF", "can11"), ["ATSH7DF", "ATCRA"]);
  assert.deepEqual(P.headerCommands("18DA10F1", "can29"), ["ATCP18", "ATSHDA10F1", "ATCRA18DAF110"]);
  assert.deepEqual(P.headerCommands("18DB33F1", "can29"), ["ATCP18", "ATSHDB33F1", "ATCRA"]);
});
