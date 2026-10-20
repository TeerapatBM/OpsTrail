"use strict";
const tokenInput = document.querySelector("#token");
const portInput = document.querySelector("#port");
const status = document.querySelector("#status");
chrome.storage.local.get(["token", "port"]).then((s) => {
  tokenInput.value = s.token || "";
  portInput.value = s.port || 8765;
});
document.querySelector("#options").addEventListener("submit", async (event) => {
  event.preventDefault();
  const token = tokenInput.value.trim();
  const port = Number(portInput.value);
  if (!/^[A-Za-z0-9_-]{43}$/.test(token) || !Number.isInteger(port) || port < 1 || port > 65535) {
    status.textContent = "กรุณาตรวจสอบ token และพอร์ต";
    return;
  }
  try {
    await chrome.storage.local.set({ token, port });
    status.textContent = "บันทึกแล้ว — เปิด OpsTrail แล้วสลับแท็บเพื่อเริ่มบันทึก";
  } catch { status.textContent = "บันทึกไม่สำเร็จ กรุณาลองใหม่"; }
});
document.querySelector("#disable").addEventListener("click", async () => {
  await chrome.storage.local.remove("token");
  tokenInput.value = "";
  status.textContent = "ปิดการบันทึกแล้ว";
});
