const dot = document.getElementById("dot");
const statusLabel = document.getElementById("statusLabel");
const statusDetail = document.getElementById("statusDetail");
const portInput = document.getElementById("port");
const tokenInput = document.getElementById("token");
const errorEl = document.getElementById("error");
const connectBtn = document.getElementById("connectBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const versionEl = document.getElementById("version");

function updateUI(status) {
  const on = status.connected;
  dot.className = `dot ${on ? "on" : "off"}`;
  statusLabel.textContent = on ? "Connected" : "Disconnected";
  statusDetail.textContent = on ? `Daemon on port ${status.port}` : "Not connected to daemon";
  if (!on && !status.paired) statusDetail.textContent = "Paste a pairing token to connect";
  portInput.value = status.port;
  versionEl.textContent = `v${status.version}`;
}

function refresh() {
  chrome.runtime.sendMessage({ type: "get-status" }, (status) => {
    if (status) updateUI(status);
  });
}

connectBtn.addEventListener("click", () => {
  const port = parseInt(portInput.value) || 9377;
  const token = tokenInput.value.trim();
  errorEl.textContent = "";
  chrome.runtime.sendMessage({ type: "connect", port, token }, (result) => {
    if (!result?.ok) errorEl.textContent = result?.error || "Connection failed";
    tokenInput.value = "";
    setTimeout(refresh, 500);
  });
});

disconnectBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "disconnect" }, () => {
    setTimeout(refresh, 200);
  });
});

refresh();
