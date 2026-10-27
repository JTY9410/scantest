// node --test tests/js
const test = require("node:test");
const assert = require("node:assert/strict");
const {
  obdPanelState,
  obdControlsLocked,
  bleChooserOptions,
} = require("../../app/static/js/components/obd-link.js");

test("기억한 진단기가 없으면 '진단기 연결하기' 안내를 띄운다", () => {
  const st = obdPanelState({ remembered: 0, ble: true, serial: true, secure: true });
  assert.equal(st.firstTime, true);
  assert.equal(st.findDisabled, false);
  assert.equal(st.reason, "");
  assert.match(st.firstMessage, /이전에 연결한 진단기가 없습니다. 진단기 연결하기를 눌러 검색하세요/);
});

test("한 번 연결한 진단기가 있으면 자동 감지만 한다", () => {
  assert.equal(obdPanelState({ remembered: 1, ble: true, secure: true }).firstTime, false);
});

test("HTTPS가 아니면 버튼을 끄고 이유를 보여준다", () => {
  const st = obdPanelState({ remembered: 0, ble: false, serial: false, secure: false });
  assert.equal(st.findDisabled, true);
  assert.equal(st.firstTime, false);
  assert.match(st.reason, /HTTPS/);
});

test("BLE가 없으면 이유를 보여주고 시리얼은 안내한다", () => {
  const st = obdPanelState({ remembered: 0, ble: false, serial: true, secure: true });
  assert.equal(st.findDisabled, true);
  assert.match(st.reason, /블루투스 클래식·USB/);
  assert.match(obdPanelState({ ble: false, serial: false }).reason, /지원하지 않습니다/);
});

// 휴대폰 Chrome: 클릭한 버튼을 requestDevice 전에 disabled 하면 페어링 창이 안 뜬다.
// searching 동안은 버튼을 잠그지 않는다(chooser는 브라우저 모달).
test("searching 상태에서는 연결 버튼을 잠그지 않는다", () => {
  assert.equal(obdControlsLocked({ state: "searching", busy: false }), false);
  assert.equal(obdControlsLocked({ state: "connecting", busy: false }), true);
  assert.equal(obdControlsLocked({ state: "ready", busy: false }), true);
  assert.equal(obdControlsLocked({ state: "idle", busy: true }), true);
  assert.equal(obdControlsLocked({ state: "idle", busy: false }), false);
});

test("BLE 선택 옵션은 빈 접두사를 빼고 optionalServices에 서비스를 둔다", () => {
  const filtered = bleChooserOptions({
    all: false,
    prefixes: ["OBD", "", "ELM", "OBD"],
    services: [0xfff0, "6e400001-b5a3-f393-e0a9-e50e24dcca9e", 0xfff0],
  });
  assert.equal(filtered.acceptAllDevices, undefined);
  assert.deepEqual(filtered.filters, [{ namePrefix: "OBD" }, { namePrefix: "ELM" }, { services: [0xfff0] }]);
  assert.deepEqual(filtered.optionalServices, [0xfff0, "6e400001-b5a3-f393-e0a9-e50e24dcca9e"]);

  const all = bleChooserOptions({ all: true, prefixes: ["OBD"], services: [0xffe0] });
  assert.equal(all.acceptAllDevices, true);
  assert.equal(all.filters, undefined);
  assert.deepEqual(all.optionalServices, [0xffe0]);
});