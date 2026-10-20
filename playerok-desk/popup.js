const status = document.getElementById("status");

chrome.storage.local.get("desk").then((stored) => {
  const desk = stored.desk || {};
  const last = desk.state && desk.state.log && desk.state.log[0];
  const mode = desk.enabled ? (desk.practice === false ? "включён" : "учебный режим") : "выключен";
  status.textContent = mode + (last ? ". " + last.text : "");
});

document.getElementById("options").addEventListener("click", () => chrome.runtime.openOptionsPage());

document.getElementById("now").addEventListener("click", async () => {
  const tabs = await chrome.tabs.query({ url: "https://playerok.com/*" });
  if (!tabs.length) {
    status.textContent = "Откройте playerok.com и войдите в аккаунт.";
    return;
  }
  status.textContent = "Проверяю…";
  const result = await chrome.tabs.sendMessage(tabs[0].id, { type: "tick" });
  status.textContent = result && result.ok ? "Готово, смотрите журнал в настройках." : (result && result.error) || "Вкладка не ответила. Обновите playerok.com.";
});
