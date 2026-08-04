(() => {
  "use strict";
  if (window.__NTC_STREAM_SOURCES_OVERLAY_V5__) return;
  document.getElementById("ntc-stream-sources-nav")?.remove();
  window.__NTC_STREAM_SOURCES_OVERLAY_V5__ = true;

  const API = "/api/v1/workspace/stream-sources";
  const style = document.createElement("style");
  style.textContent = `
    #ntc-stream-sources-panel{position:fixed;top:78px;right:18px;z-index:2147482980;width:min(480px,calc(100vw - 36px));max-height:calc(100vh - 96px);overflow:auto;background:#101820;color:#edf4f7;border:1px solid #385061;border-radius:8px;box-shadow:0 14px 44px #000c;font:14px/1.4 system-ui,sans-serif}
    #ntc-stream-sources-panel[hidden]{display:none}
    #ntc-stream-sources-panel *{box-sizing:border-box}
    .ntc-ss-header{display:flex;align-items:center;justify-content:space-between;padding:16px 18px;border-bottom:1px solid #304451}
    .ntc-ss-title{font-size:18px;font-weight:700}.ntc-ss-subtitle{color:#9db0bb;font-size:12px;margin-top:2px}
    .ntc-ss-close{border:1px solid #385061;background:#172935;color:#edf4f7;border-radius:4px;padding:7px 10px;cursor:pointer}
    .ntc-ss-body{padding:16px 18px}.ntc-ss-note{color:#b6c5cc;background:#142631;border:1px solid #2e4b5b;border-radius:6px;padding:10px 12px;margin-bottom:14px;font-size:12px}
    .ntc-ss-label{display:block;color:#c9d5da;font-size:12px;margin:12px 0 5px}.ntc-ss-input{width:100%;border:1px solid #3b5665;border-radius:4px;background:#0b1218;color:#edf4f7;padding:10px 11px;outline:none}.ntc-ss-input:focus{border-color:#76b900;box-shadow:0 0 0 1px #76b900}
    .ntc-ss-actions{display:flex;justify-content:flex-end;margin-top:14px}.ntc-ss-primary{border:1px solid #76b900;background:#76b900;color:#071018;border-radius:4px;padding:9px 14px;font-weight:700;cursor:pointer}.ntc-ss-primary:disabled{opacity:.55;cursor:wait}
    .ntc-ss-message{min-height:20px;color:#f0c75e;font-size:12px;margin-top:10px}.ntc-ss-message.error{color:#ff9b9b}
    .ntc-ss-list{display:grid;gap:8px;margin-top:18px}.ntc-ss-card{border:1px solid #2e4b5b;border-radius:6px;padding:11px 12px;background:#142631}.ntc-ss-row{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.ntc-ss-name{font-weight:700;overflow-wrap:anywhere}.ntc-ss-meta{color:#a9bbc4;font-size:12px;margin-top:4px}.ntc-ss-badge{white-space:nowrap;border-radius:4px;padding:3px 6px;background:#31505f;color:#e9f3f6;font-size:11px}.ntc-ss-badge.online{background:#3f6500;color:#f3ffd7}.ntc-ss-badge.offline{background:#46515a}.ntc-ss-delete{margin-top:9px;border:1px solid #6c4141;background:#27191b;color:#ffb1b1;border-radius:4px;padding:6px 9px;cursor:pointer}.ntc-ss-empty{color:#9db0bb;text-align:center;padding:18px 8px}
    #ntc-vm-section-tabs{display:flex;gap:8px;align-items:center;padding:12px 24px;border-bottom:1px solid #d1d5db;background:#f9fafb}
    #ntc-vm-section-tabs button{border:1px solid #9ca3af;border-radius:4px;background:#fff;color:#111827;padding:8px 13px;font:600 13px system-ui,sans-serif;cursor:pointer}
    #ntc-vm-section-tabs button[aria-selected=true]{border-color:#76b900;background:#76b900;color:#071018}
    #ntc-vm-processed-pane{display:flex;flex:1;min-height:0;flex-direction:column;overflow:auto;padding:20px 24px;background:#f9fafb;color:#111827}
    #ntc-vm-processed-pane[hidden]{display:none}
    .ntc-vm-processed-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}.ntc-vm-processed-head h2{font-size:20px;margin:0}.ntc-vm-processed-head button{border:1px solid #9ca3af;border-radius:4px;background:#fff;color:#111827;padding:8px 12px;cursor:pointer}
    .ntc-vm-processed-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}.ntc-vm-processed-card{border:1px solid #d1d5db;border-radius:7px;padding:12px;background:#fff}.ntc-vm-processed-card h3{font-size:14px;margin:0 0 6px;overflow-wrap:anywhere}.ntc-vm-processed-card p{color:#6b7280;font-size:12px;margin:5px 0}.ntc-vm-processed-card video{display:block;width:100%;max-height:180px;background:#000;margin:10px 0}.ntc-vm-processed-card button{border:1px solid #76b900;border-radius:4px;background:#76b900;color:#071018;padding:7px 10px;font-weight:700;cursor:pointer}.ntc-vm-processed-empty{color:#6b7280;padding:18px 0}.ntc-vm-processed-error{color:#b91c1c;padding:10px 0}
    html.dark #ntc-vm-section-tabs,body.dark #ntc-vm-section-tabs{background:#0b1218;border-color:#263b49}
    html.dark #ntc-vm-section-tabs button,body.dark #ntc-vm-section-tabs button{border-color:#385061;background:#182733;color:#eaf2f5}
    html.dark #ntc-vm-section-tabs button[aria-selected=true],body.dark #ntc-vm-section-tabs button[aria-selected=true]{background:#76b900;color:#071018;border-color:#76b900}
    html.dark #ntc-vm-processed-pane,body.dark #ntc-vm-processed-pane{background:#000;color:#eef5f8}
    html.dark .ntc-vm-processed-head button,body.dark .ntc-vm-processed-head button{border-color:#385061;background:#182733;color:#eaf2f5}
    html.dark .ntc-vm-processed-card,body.dark .ntc-vm-processed-card{border-color:#2e4b5b;background:#142631}
    html.dark .ntc-vm-processed-card p,body.dark .ntc-vm-processed-card p{color:#a9bbc4}
    html.dark .ntc-vm-processed-empty,body.dark .ntc-vm-processed-empty{color:#9db0bb}
    html.dark .ntc-vm-processed-error,body.dark .ntc-vm-processed-error{color:#ff9b9b}
    #ntc-upload-stream-button{margin-left:0}
    #ntc-live-card-button{position:absolute;right:10px;bottom:10px;z-index:3;border:1px solid #76b900;border-radius:4px;background:#76b900;color:#071018;padding:7px 10px;font:700 12px system-ui,sans-serif;cursor:pointer;box-shadow:0 2px 8px #0008}
    #ntc-live-card-button:hover{background:#8bd400}
    #ntc-live-viewer{position:fixed;inset:0;z-index:2147482990;background:#000b;display:flex;align-items:center;justify-content:center;padding:28px}
    #ntc-live-viewer[hidden]{display:none}
    .ntc-live-dialog{position:relative;width:min(1120px,96vw);max-height:92vh;background:#101820;border:1px solid #76b900;border-radius:7px;box-shadow:0 16px 60px #000c;overflow:hidden}
    .ntc-live-head{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;color:#edf4f7;font:700 16px system-ui,sans-serif;border-bottom:1px solid #385061}
    .ntc-live-head span{color:#9bd12f;font-size:12px;margin-left:8px}
    .ntc-live-close{border:1px solid #385061;background:#172935;color:#edf4f7;border-radius:4px;padding:6px 10px;cursor:pointer}
    .ntc-live-image{display:block;width:100%;max-height:calc(92vh - 58px);object-fit:contain;background:#000}
    @media (max-width:600px){#ntc-stream-sources-panel{top:70px;right:8px;width:calc(100vw - 16px);max-height:calc(100vh - 80px)}}
  `;
  document.head.appendChild(style);

  const make = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  };

  let panel;
  let message;
  let list;
  let addButton;
  let urlInput;
  let nameInput;
  let processedPane;
  let processedList;
  let processedError;
  const VLM_STORE_API = "/api/v1/workspace/vlm-tests/store";
  const CAM01_LIVE_URL = "/api/v1/workspace/cameras/cam-01/live.mjpeg";
  let liveViewer;

  function showMessage(text, error) {
    if (!message) return;
    message.textContent = text || "";
    message.classList.toggle("error", Boolean(error));
  }

  async function request(url, options) {
    const response = await fetch(url, { credentials: "same-origin", ...options });
    let value = {};
    try { value = await response.json(); } catch (_) { /* handled below */ }
    if (!response.ok) throw new Error(value.message || value.code || `Request failed (${response.status})`);
    return value;
  }

  function statusClass(state) {
    return ["online", "healthy", "connected", "running", "active"].includes(String(state).toLowerCase()) ? "online" :
      ["offline", "stopped", "failed"].includes(String(state).toLowerCase()) ? "offline" : "";
  }

  function renderSources(sources) {
    list.replaceChildren();
    if (!sources.length) {
      list.appendChild(make("div", "Chưa có nguồn stream nào.", "ntc-ss-empty"));
      return;
    }
    sources.forEach((source) => {
      const card = make("div", undefined, "ntc-ss-card");
      const row = make("div", undefined, "ntc-ss-row");
      const details = make("div");
      details.appendChild(make("div", source.name || source.source_id, "ntc-ss-name"));
      const metadata = source.metadata || {};
      details.appendChild(make("div", `${source.source_type || "RTSP"} · ${metadata.codec || "unknown"} · ${metadata.resolution || "unknown"}`, "ntc-ss-meta"));
      const badge = make("span", source.state || "unknown", `ntc-ss-badge ${statusClass(source.state)}`);
      row.append(details, badge);
      card.appendChild(row);
      if (source.can_delete) {
        const remove = make("button", "Xoá nguồn", "ntc-ss-delete");
        remove.type = "button";
        remove.addEventListener("click", async () => {
          if (!window.confirm(`Xoá nguồn ${source.name || source.source_id}?`)) return;
          remove.disabled = true;
          try {
            await request(`${API}/${encodeURIComponent(source.source_id)}`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: "{}" });
            showMessage("Đã xoá nguồn stream.", false);
            await loadSources();
          } catch (error) {
            showMessage(error.message || "Không thể xoá nguồn stream.", true);
            remove.disabled = false;
          }
        });
        card.appendChild(remove);
      }
      list.appendChild(card);
    });
  }

  async function loadSources() {
    try {
      const value = await request(API, { method: "GET" });
      renderSources(Array.isArray(value.sources) ? value.sources : []);
    } catch (error) {
      renderSources([]);
      showMessage(error.message || "Không thể tải nguồn stream.", true);
    }
  }

  async function addSource(event) {
    event.preventDefault();
    const url = urlInput.value.trim();
    const name = nameInput.value.trim();
    if (!/^rtsp:\/\/[^\s]+$/i.test(url)) {
      showMessage("RTSP URL phải bắt đầu bằng rtsp://.", true);
      return;
    }
    if (!name) {
      showMessage("Vui lòng nhập tên nguồn stream.", true);
      return;
    }
    addButton.disabled = true;
    showMessage("Đang kết nối và đăng ký nguồn stream…", false);
    try {
      await request(API, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ schema_version: "1.0.0", store_id: "store-001", url, name }) });
      urlInput.value = "";
      nameInput.value = "";
      showMessage("Đã gửi yêu cầu đăng ký nguồn stream.", false);
      await loadSources();
    } catch (error) {
      showMessage(error.message || "Không thể thêm nguồn stream.", true);
    } finally {
      addButton.disabled = false;
    }
  }

  function buildPanel() {
    if (panel) return panel;
    panel = make("section");
    panel.id = "ntc-stream-sources-panel";
    panel.hidden = true;
    const header = make("div", undefined, "ntc-ss-header");
    const titleGroup = make("div");
    titleGroup.appendChild(make("div", "Upload Stream", "ntc-ss-title"));
    titleGroup.appendChild(make("div", "Đăng ký nguồn RTSP vào Video Management", "ntc-ss-subtitle"));
    const close = make("button", "×", "ntc-ss-close");
    close.type = "button";
    close.addEventListener("click", () => { panel.hidden = true; });
    header.append(titleGroup, close);
    const body = make("div", undefined, "ntc-ss-body");
    body.appendChild(make("div", "Thông tin xác thực chỉ được chuyển qua gateway để VIOS kết nối; không hiển thị lại trong danh sách và không ghi vào camera registry của project.", "ntc-ss-note"));
    const form = make("form");
    const urlLabel = make("label", "RTSP URL", "ntc-ss-label");
    urlInput = make("input", undefined, "ntc-ss-input");
    urlInput.type = "url"; urlInput.required = true; urlInput.placeholder = "rtsp://user:password@camera:554/stream";
    const nameLabel = make("label", "Tên nguồn", "ntc-ss-label");
    nameInput = make("input", undefined, "ntc-ss-input");
    nameInput.required = true; nameInput.maxLength = 80; nameInput.placeholder = "Warehouse Camera 01";
    const actions = make("div", undefined, "ntc-ss-actions");
    addButton = make("button", "+ Upload Stream", "ntc-ss-primary");
    addButton.type = "submit";
    actions.appendChild(addButton);
    message = make("div", undefined, "ntc-ss-message");
    list = make("div", undefined, "ntc-ss-list");
    form.append(urlLabel, urlInput, nameLabel, nameInput, actions, message);
    form.addEventListener("submit", addSource);
    body.append(form, list);
    panel.append(header, body);
    document.body.appendChild(panel);
    return panel;
  }

  function openPanel() {
    buildPanel().hidden = false;
    showMessage("", false);
    loadSources();
  }

  function renderProcessedAssets(assets) {
    if (!processedList) return;
    processedList.replaceChildren();
    if (!assets.length) {
      processedList.appendChild(make("div", "Chưa có video nào được Save to Store sau khi VLM xử lý.", "ntc-vm-processed-empty"));
      return;
    }
    assets.forEach((asset) => {
      const assetId = String(asset.asset_id || "");
      if (!/^[0-9a-f]{64}$/.test(assetId)) return;
      const card = make("article", undefined, "ntc-vm-processed-card");
      card.appendChild(make("h3", asset.filename || assetId.slice(0, 12)));
      card.appendChild(make("p", `${asset.camera_id || "cam-01"} · ${asset.verdict || "VLM complete"}`));
      if (asset.created_at) card.appendChild(make("p", asset.created_at));
      const video = document.createElement("video");
      video.controls = true;
      video.preload = "metadata";
      video.src = `${VLM_STORE_API}/${assetId}/media`;
      card.appendChild(video);
      const launch = make("button", "Launch VLM");
      launch.type = "button";
      launch.addEventListener("click", async () => {
        launch.disabled = true;
        if (processedError) processedError.textContent = "Đang chạy lại VLM…";
        try {
          await request(`${VLM_STORE_API}/${assetId}/launch`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
          if (processedError) processedError.textContent = "Đã đưa video vào hàng đợi VLM.";
        } catch (error) {
          if (processedError) processedError.textContent = error.message || "Không thể launch VLM.";
        } finally {
          launch.disabled = false;
        }
      });
      card.appendChild(launch);
      processedList.appendChild(card);
    });
  }

  async function loadProcessedAssets() {
    if (!processedPane) return;
    try {
      const value = await request(VLM_STORE_API, { method: "GET" });
      if (processedError) processedError.textContent = "";
      renderProcessedAssets(Array.isArray(value.assets) ? value.assets : []);
    } catch (error) {
      if (processedError) processedError.textContent = error.message || "Không thể tải VLM Store.";
      renderProcessedAssets([]);
    }
  }

  function closeLiveViewer() {
    if (!liveViewer) return;
    liveViewer.hidden = true;
    liveViewer.querySelector("img")?.removeAttribute("src");
  }

  function openLiveViewer() {
    if (!liveViewer) {
      liveViewer = make("section");
      liveViewer.id = "ntc-live-viewer";
      liveViewer.hidden = true;
      const dialog = make("div", undefined, "ntc-live-dialog");
      const head = make("div", undefined, "ntc-live-head");
      const title = make("div");
      title.append("cam-01 ");
      title.appendChild(make("span", "LIVE"));
      const close = make("button", "×", "ntc-live-close");
      close.type = "button";
      close.addEventListener("click", closeLiveViewer);
      head.append(title, close);
      const image = document.createElement("img");
      image.className = "ntc-live-image";
      image.alt = "cam-01 live stream";
      dialog.append(head, image);
      liveViewer.appendChild(dialog);
      liveViewer.addEventListener("click", (event) => {
        if (event.target === liveViewer) closeLiveViewer();
      });
      document.body.appendChild(liveViewer);
    }
    liveViewer.hidden = false;
    const image = liveViewer.querySelector("img");
    if (image && image.src !== `${window.location.origin}${CAM01_LIVE_URL}`) image.src = CAM01_LIVE_URL;
  }

  function findCam01Card() {
    const name = Array.from(document.querySelectorAll("h1,h2,h3,h4,p,span,div"))
      .find((element) => element.children.length === 0 && element.textContent.trim() === "cam-01");
    if (!name) return null;
    let current = name;
    for (let index = 0; index < 8 && current; index += 1, current = current.parentElement) {
      if (current.querySelector("img")) return current.closest(".group") || current;
    }
    return null;
  }

  function ensureCam01LiveCard() {
    const card = findCam01Card();
    if (!card) return;
    const image = card.querySelector("img");
    if (image) {
      image.dataset.ntcLivePresentation = "true";
      if (image.getAttribute("src") !== CAM01_LIVE_URL) image.setAttribute("src", CAM01_LIVE_URL);
    }
    if (!card.querySelector("#ntc-live-card-button")) {
      const live = make("button", "Open Live", undefined);
      live.id = "ntc-live-card-button";
      live.type = "button";
      live.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        openLiveViewer();
      });
      card.style.position = "relative";
      card.appendChild(live);
    }
    if (card.dataset.ntcLiveClickHandler !== "true") {
      card.dataset.ntcLiveClickHandler = "true";
      card.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const button = target.closest("button");
        if (target.closest("#ntc-live-card-button") || target.closest("input[type=checkbox]") || target.closest("[title*=Chat]") || (button && button.textContent.includes("Chat"))) return;
        if (target.closest("img") || target.closest("button")) {
          event.preventDefault();
          event.stopPropagation();
          openLiveViewer();
        }
      }, true);
    }
  }

  function makeSectionTabs(root, mainPane) {
    const tabs = make("nav");
    tabs.id = "ntc-vm-section-tabs";
    const streaming = make("button", "Streaming");
    const processed = make("button", "VLM Processed Videos");
    streaming.type = "button";
    processed.type = "button";
    streaming.setAttribute("aria-selected", "true");
    processed.setAttribute("aria-selected", "false");
    tabs.append(streaming, processed);
    processedPane = make("section");
    processedPane.id = "ntc-vm-processed-pane";
    processedPane.hidden = true;
    const head = make("div", undefined, "ntc-vm-processed-head");
    const title = make("h2", "VLM Processed Videos");
    const refresh = make("button", "Refresh");
    refresh.type = "button";
    refresh.addEventListener("click", loadProcessedAssets);
    head.append(title, refresh);
    processedError = make("div", undefined, "ntc-vm-processed-error");
    processedList = make("div", undefined, "ntc-vm-processed-list");
    processedPane.append(head, processedError, processedList);

    const select = (section) => {
      const isStreaming = section === "streaming";
      streaming.setAttribute("aria-selected", String(isStreaming));
      processed.setAttribute("aria-selected", String(!isStreaming));
      mainPane.style.display = isStreaming ? "" : "none";
      processedPane.hidden = isStreaming;
      if (!isStreaming) loadProcessedAssets();
    };
    streaming.addEventListener("click", () => select("streaming"));
    processed.addEventListener("click", () => select("processed"));
    root.insertBefore(tabs, root.firstElementChild);
    root.appendChild(processedPane);
  }

  function ensureVideoManagementControls() {
    const uploadButton = Array.from(document.querySelectorAll("button")).find((button) =>
      button.textContent.trim().includes("Upload Video") && !button.id
    );
    if (!uploadButton) return;
    const toolbar = uploadButton.closest("div.min-w-0.max-w-full");
    if (!toolbar || toolbar.id === "ntc-vm-toolbar") return;
    toolbar.id = "ntc-vm-toolbar";
    Array.from(toolbar.querySelectorAll("button")).forEach((button) => {
      if (button.textContent.trim().includes("Add RTSP")) button.style.display = "none";
    });
    if (!toolbar.querySelector("#ntc-upload-stream-button")) {
      const streamButton = uploadButton.cloneNode(true);
      streamButton.id = "ntc-upload-stream-button";
      streamButton.textContent = "+ Upload Stream";
      streamButton.title = "Upload Stream";
      streamButton.disabled = false;
      streamButton.addEventListener("click", openPanel);
      uploadButton.insertAdjacentElement("afterend", streamButton);
    }
    const root = toolbar.parentElement;
    if (!root || root.querySelector("#ntc-vm-section-tabs")) return;
    const mainPane = Array.from(root.children).find((child) => child !== toolbar && child.tagName !== "INPUT");
    if (!mainPane) return;
    makeSectionTabs(root, mainPane);
  }

  ensureVideoManagementControls();
  const observer = new MutationObserver(() => {
    ensureVideoManagementControls();
    ensureCam01LiveCard();
  });
  observer.observe(document.body, { childList: true, subtree: true });
  ensureCam01LiveCard();
  window.setInterval(ensureCam01LiveCard, 2000);
})();
