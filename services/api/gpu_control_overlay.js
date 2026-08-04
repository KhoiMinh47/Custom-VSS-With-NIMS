(() => {
  "use strict";

  if (window.__NTC_GPU_CONTROL_OVERLAY_V1__) return;
  window.__NTC_GPU_CONTROL_OVERLAY_V1__ = true;

  const API = "/api/v1/gpu-control/models";
  const state = { models: [], panelOpen: false, error: "", notice: "", loading: "" };

  const css = `
    #ntc-gpu-control-launcher{position:fixed;top:28px;right:160px;z-index:2147482990;border:1px solid #385061;border-radius:999px;background:#182733;color:#eaf2f5;box-shadow:0 6px 18px #0008;font:700 13px/1.2 system-ui,sans-serif;padding:10px 14px;cursor:pointer;pointer-events:auto}
    #ntc-gpu-control-launcher:hover,#ntc-gpu-control-launcher:focus-visible{border-color:#76b900;outline:none}
    #ntc-gpu-control-panel{position:fixed;top:70px;right:18px;z-index:2147482991;width:min(340px,calc(100vw - 36px));background:#101820;color:#eef5f8;border:1px solid #334b5b;border-radius:8px;box-shadow:0 12px 40px #000b;font:14px/1.4 system-ui,sans-serif;padding:14px}
    #ntc-gpu-control-panel[hidden]{display:none}
    #ntc-gpu-control-panel *{box-sizing:border-box}
    .ntc-gpu-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
    .ntc-gpu-head strong{font-size:15px}.ntc-gpu-head small{display:block;color:#9eb3bf;margin-top:2px}
    .ntc-gpu-close{border:0;background:transparent;color:#c9d4d9;font-size:22px;cursor:pointer}
    .ntc-gpu-row{display:flex;align-items:center;gap:10px;border:1px solid #2e4654;border-radius:7px;background:#14222c;padding:10px;margin-top:8px}
    .ntc-gpu-dot{width:11px;height:11px;flex:0 0 11px;border-radius:50%;background:#697780;box-shadow:0 0 0 3px #69778033}
    .ntc-gpu-dot.online{background:#76b900;box-shadow:0 0 0 3px #76b90033}.ntc-gpu-dot.busy{background:#e4ad2f;box-shadow:0 0 0 3px #e4ad2f33}.ntc-gpu-dot.error{background:#e05252;box-shadow:0 0 0 3px #e0525233}
    .ntc-gpu-info{min-width:0;flex:1}.ntc-gpu-info strong{display:block}.ntc-gpu-info small{display:block;color:#9eb3bf;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .ntc-gpu-toggle{border:1px solid #385061;border-radius:5px;background:#182733;color:#eaf2f5;padding:6px 10px;cursor:pointer;font-weight:700;font-size:12px}.ntc-gpu-toggle.on{background:#76b900;border-color:#76b900;color:#071018}.ntc-gpu-toggle:disabled{opacity:.45;cursor:not-allowed}
    .ntc-gpu-policy{margin:12px 0 0;padding-top:10px;border-top:1px solid #263b49;color:#9eb3bf;font-size:12px}.ntc-gpu-policy b{color:#dce8eb}
    .ntc-gpu-notice{min-height:18px;margin:8px 0 0;color:#9cf0b0;font-size:12px}.ntc-gpu-notice.error{color:#ffb1b1}
    @media (max-width:600px){#ntc-gpu-control-launcher{top:70px;right:108px}#ntc-gpu-control-panel{top:112px}}
  `;

  function node(tag, text, className) {
    const value = document.createElement(tag);
    if (text !== undefined) value.textContent = text;
    if (className) value.className = className;
    return value;
  }

  function button(text, handler, className) {
    const value = node("button", text, className);
    value.type = "button";
    value.addEventListener("click", handler);
    return value;
  }

  async function api(path, options) {
    const response = await fetch(path, { cache: "no-store", ...options });
    const value = await response.json().catch(() => ({ message: `HTTP ${response.status}` }));
    if (!response.ok) throw new Error(value.message || value.code || `HTTP ${response.status}`);
    return value;
  }

  function statusText(model) {
    if (model.state === "online") return "Online";
    if (model.state === "starting") return "Đang bật…";
    if (model.state === "stopping") return "Đang tắt…";
    if (model.state === "error") return "Lỗi bật/tắt";
    return "Offline";
  }

  function render() {
    if (!panel) return;
    panel.hidden = !state.panelOpen;
    if (!state.panelOpen) return;
    const list = panel.querySelector(".ntc-gpu-list");
    list.replaceChildren();
    state.models.forEach((model) => {
      const row = node("div", undefined, "ntc-gpu-row");
      const dot = node("span", undefined, `ntc-gpu-dot ${model.state === "online" ? "online" : ["starting", "stopping"].includes(model.state) ? "busy" : model.state === "error" ? "error" : ""}`);
      dot.title = statusText(model);
      const info = node("div", undefined, "ntc-gpu-info");
      info.append(node("strong", `${model.short_title} · ${statusText(model)}`));
      info.append(node("small", model.message || model.model));
      const toggle = button(model.enabled ? "Tắt" : "Bật", () => toggleModel(model), `ntc-gpu-toggle${model.enabled ? " on" : ""}`);
      toggle.disabled = Boolean(state.loading) || ["starting", "stopping"].includes(model.state);
      toggle.setAttribute("aria-label", `${model.enabled ? "Tắt" : "Bật"} ${model.short_title}`);
      row.append(dot, info, toggle);
      list.append(row);
    });
    if (!state.models.length) list.append(node("div", "Đang đọc trạng thái GPU…", "ntc-gpu-info"));
    const notice = panel.querySelector(".ntc-gpu-notice");
    notice.textContent = state.error || state.notice || "";
    notice.className = `ntc-gpu-notice${state.error ? " error" : ""}`;
  }

  async function refresh() {
    try {
      const value = await api(API);
      state.models = Array.isArray(value.models) ? value.models : [];
      state.error = "";
    } catch (error) {
      state.error = error.message || "GPU control backend unavailable";
    }
    render();
  }

  async function toggleModel(model) {
    state.loading = model.id;
    state.error = "";
    state.notice = `${model.short_title}: đang gửi lệnh ${model.enabled ? "tắt" : "bật"}…`;
    render();
    try {
      await api(`${API}/${model.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !model.enabled, confirmed: true }),
      });
      state.notice = `${model.short_title}: đã nhận lệnh ${model.enabled ? "tắt" : "bật"}.`;
    } catch (error) {
      state.error = error.message || "Không thể thay đổi trạng thái model";
      state.notice = "";
    }
    state.loading = "";
    await refresh();
  }

  let panel;
  function init() {
    const style = node("style");
    style.textContent = css;
    document.head.append(style);
    const launcher = button("GPU", () => { state.panelOpen = !state.panelOpen; render(); if (state.panelOpen) refresh(); }, "");
    launcher.id = "ntc-gpu-control-launcher";
    launcher.setAttribute("aria-label", "Open GPU model controls");
    launcher.title = "LLM / VLM on-off control";
    document.body.append(launcher);
    panel = node("aside");
    panel.id = "ntc-gpu-control-panel";
    panel.hidden = true;
    const head = node("header", undefined, "ntc-gpu-head");
    const title = node("div");
    title.append(node("strong", "GPU Models"));
    title.append(node("small", "LLM / VLM controls"));
    head.append(title, button("×", () => { state.panelOpen = false; render(); }, "ntc-gpu-close"));
    panel.append(head, node("div", undefined, "ntc-gpu-list"));
    panel.append(node("div", "", "ntc-gpu-notice"));
    const policy = node("div", undefined, "ntc-gpu-policy");
    policy.append(node("b", "RT-CV: "), node("span", "chỉ tự bật trong luồng upload VLM Test."));
    panel.append(policy);
    document.body.append(panel);
    render();
    refresh();
    window.setInterval(refresh, 3000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
