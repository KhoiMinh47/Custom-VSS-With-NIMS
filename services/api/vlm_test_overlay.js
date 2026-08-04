(() => {
  "use strict";

  if (window.__NTC_VLM_TEST_OVERLAY_V5__) return;
  document.getElementById("ntc-vlm-test-launcher")?.remove();
  document.getElementById("ntc-vlm-test-drawer")?.remove();
  window.__NTC_VLM_TEST_OVERLAY_V5__ = true;

  const API = "/api/v1/workspace/vlm-tests";
  const state = { tab: "upload", files: [], jobs: [], assets: [], candidates: [], error: "", uploading: false };

  const css = `
    #ntc-vlm-test-launcher{position:fixed;top:28px;right:70px;z-index:2147483000;border:1px solid #76b900;border-radius:999px;background:#76b900;color:#071018;box-shadow:0 6px 18px #0008;font:700 13px/1.2 system-ui,sans-serif;padding:10px 15px;cursor:pointer;white-space:nowrap;pointer-events:auto}
    #ntc-vlm-test-launcher:hover,#ntc-vlm-test-launcher:focus-visible{background:#76b900;color:#071018;outline:none}
    #ntc-vlm-test-drawer{position:fixed;top:0;right:0;z-index:2147483001;width:min(560px,calc(100vw - 20px));height:100vh;display:flex;flex-direction:column;background:#101820;color:#eef5f8;border-left:1px solid #334b5b;box-shadow:-18px 0 48px #0008;font:14px/1.4 system-ui,sans-serif}
    #ntc-vlm-test-drawer[hidden]{display:none}
    #ntc-vlm-test-drawer *{box-sizing:border-box}
    .ntc-vlm-head{display:flex;align-items:center;justify-content:space-between;padding:18px 20px;border-bottom:1px solid #263b49}
    .ntc-vlm-head h2{font-size:18px;margin:0}.ntc-vlm-head small{display:block;color:#9eb3bf;margin-top:3px}
    .ntc-vlm-close{border:0;background:transparent;color:#c9d4d9;font-size:24px;cursor:pointer;padding:0 4px}
    .ntc-vlm-tabs{display:flex;gap:4px;padding:10px 14px;border-bottom:1px solid #263b49;background:#0b1218}
    .ntc-vlm-tabs button,.ntc-vlm-action{border:1px solid #385061;border-radius:5px;background:#182733;color:#eaf2f5;padding:8px 11px;cursor:pointer}
    .ntc-vlm-tabs button[aria-selected=true]{background:#76b900;color:#071018;border-color:#76b900;font-weight:700}
    .ntc-vlm-body{overflow:auto;flex:1;padding:16px 18px}.ntc-vlm-status{min-height:21px;color:#a9bbc3;margin:0 0 12px}
    .ntc-vlm-drop{border:1px dashed #718994;border-radius:8px;padding:22px;text-align:center;background:#14232d;cursor:pointer}
    .ntc-vlm-drop:hover,.ntc-vlm-drop.drag{border-color:#76b900;background:#1c2f1e}.ntc-vlm-drop strong{display:block;color:#fff;margin-bottom:4px}
    .ntc-vlm-list{display:grid;gap:8px;margin-top:12px}.ntc-vlm-file,.ntc-vlm-card{border:1px solid #2e4654;border-radius:7px;background:#14222c;padding:11px}
    .ntc-vlm-file{display:flex;align-items:center;gap:8px}.ntc-vlm-file span:first-child{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .ntc-vlm-muted{color:#9eb3bf}.ntc-vlm-badge{display:inline-block;border-radius:4px;padding:2px 6px;font-size:11px;background:#2a414e;color:#d9e5e9;margin-right:5px}
    .ntc-vlm-badge.confirmed{background:#214d30;color:#9cf0b0}.ntc-vlm-badge.rejected{background:#5d2830;color:#ffb1b1}.ntc-vlm-badge.uncertain{background:#5a4820;color:#ffe39b}
    .ntc-vlm-card h3{font-size:14px;margin:0 0 5px}.ntc-vlm-card p{margin:5px 0;color:#c0cdd2}.ntc-vlm-card video{width:100%;max-height:180px;background:#000;margin-top:8px}
    .ntc-vlm-row{display:flex;align-items:center;justify-content:space-between;gap:8px}.ntc-vlm-row+.ntc-vlm-row{margin-top:8px}
    .ntc-vlm-action{font-size:12px;white-space:nowrap}.ntc-vlm-action.primary{background:#76b900;border-color:#76b900;color:#071018;font-weight:700}.ntc-vlm-action:disabled{opacity:.45;cursor:not-allowed}
    .ntc-vlm-danger{color:#ffb1b1}.ntc-vlm-warning{color:#ffe39b}.ntc-vlm-ok{color:#9cf0b0}
    .ntc-vlm-footer{padding:12px 18px;border-top:1px solid #263b49;display:flex;justify-content:space-between;gap:8px}.ntc-vlm-footer button{flex:1}
    @media (max-width:600px){#ntc-vlm-test-launcher{top:70px;right:18px}}
  `;

  function node(tag, text, className) {
    const value = document.createElement(tag);
    if (text !== undefined) value.textContent = text;
    if (className) value.className = className;
    return value;
  }

  function button(text, handler, className) {
    const value = node("button", text, `ntc-vlm-action${className ? ` ${className}` : ""}`);
    value.type = "button";
    value.addEventListener("click", handler);
    return value;
  }

  async function api(path, options) {
    const response = await fetch(`${API}${path}`, { cache: "no-store", ...options });
    const value = await response.json().catch(() => ({ message: `HTTP ${response.status}` }));
    if (!response.ok) throw new Error(value.message || value.code || `HTTP ${response.status}`);
    return value;
  }

  function upload(file) {
    return new Promise((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open("POST", `${API}/uploads`);
      request.setRequestHeader("X-File-Name", file.name);
      request.setRequestHeader("Content-Type", file.type || (file.name.toLowerCase().endsWith(".mkv") ? "video/x-matroska" : "video/mp4"));
      request.setRequestHeader("Idempotency-Key", `ui-${crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${file.name}`}`);
      request.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) file.__ntcProgress = Math.round((event.loaded / event.total) * 100);
        render();
      });
      request.addEventListener("load", () => {
        let value = {};
        try { value = JSON.parse(request.responseText || "{}"); } catch (_) {}
        if (request.status >= 200 && request.status < 300) resolve(value);
        else reject(new Error(value.message || value.code || `Upload failed (${request.status})`));
      });
      request.addEventListener("error", () => reject(new Error("Upload request failed")));
      request.addEventListener("abort", () => reject(new Error("Upload cancelled")));
      request.send(file);
    });
  }

  async function refresh() {
    try {
      const values = await Promise.all([
        api("/jobs"),
        api("/store"),
        api("/realtime/candidates"),
      ]);
      state.jobs = values[0].jobs || [];
      state.assets = values[1].assets || [];
      state.candidates = values[2].candidates || [];
      state.error = "";
    } catch (error) {
      state.error = error.message || "VLM Test backend unavailable";
    }
    render();
  }

  function enqueueFiles(files) {
    const additions = files.filter((file) => !state.files.includes(file));
    if (!additions.length) return;
    state.files.push(...additions);
    render();
    processUploadQueue();
  }

  async function processUploadQueue() {
    if (state.uploading) return;
    state.uploading = true;
    render();
    while (true) {
      const file = state.files.find((item) => !item.__ntcUploading && !item.__ntcFailed);
      if (!file) break;
      file.__ntcUploading = true;
      file.__ntcProgress = 0;
      render();
      try {
        await upload(file);
        state.files = state.files.filter((item) => item !== file);
      } catch (error) {
        file.__ntcUploading = false;
        file.__ntcFailed = true;
        file.__ntcError = error.message || "Upload failed";
        state.error = `${file.name}: ${file.__ntcError}`;
      }
      await refresh();
    }
    state.uploading = false;
    render();
  }

  async function launchJob(job) {
    const retryRtcv = ["queued_for_rtcv", "awaiting_rtcv_candidate", "no_rtcv_candidate"].includes(job.status) ||
      (job.status === "failed" && !job.candidate_event);
    const action = retryRtcv ? "rtcv-start" : "launch";
    try { await api(`/jobs/${job.job_id}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); }
    catch (error) { state.error = error.message || "Launch failed"; }
    await refresh();
  }

  async function saveJob(jobId) {
    try { await api(`/jobs/${jobId}/save`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); }
    catch (error) { state.error = error.message || "Save failed"; }
    await refresh();
  }

  async function launchRealtime(incidentId) {
    try { await api(`/realtime/${incidentId}/launch`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); }
    catch (error) { state.error = error.message || "Realtime launch failed"; }
    await refresh();
  }

  async function launchStore(assetId) {
    try { await api(`/store/${assetId}/launch`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); }
    catch (error) { state.error = error.message || "Store launch failed"; }
    await refresh();
  }

  function statusClass(value) {
    if (value === "confirmed" || value === "rejected" || value === "uncertain") return value;
    return "";
  }

  function renderJobs(parent) {
    const jobs = node("div", undefined, "ntc-vlm-list");
    if (!state.jobs.length) jobs.append(node("p", "No VLM-test jobs yet.", "ntc-vlm-muted"));
    state.jobs.slice(0, 30).forEach((job) => {
      const card = node("article", undefined, "ntc-vlm-card");
      const header = node("div", undefined, "ntc-vlm-row");
      const title = node("h3", job.filename || job.job_id.slice(0, 12));
      header.append(title);
      const badge = node("span", job.verdict || job.status || "pending", `ntc-vlm-badge ${statusClass(job.verdict)}`);
      header.append(badge);
      card.append(header);
      card.append(node("p", `${job.source_type || "video"} · ${job.camera_id || "cam-01"} · ${job.storage_state || "staging_only"}`, "ntc-vlm-muted"));
      if (job.reason) card.append(node("p", job.reason));
      if (job.rtcv_message) card.append(node("p", job.rtcv_message, "ntc-vlm-muted"));
      const actions = node("div", undefined, "ntc-vlm-row");
      if (["ready_to_launch", "waiting_for_gpu", "failed", "queued_for_rtcv", "awaiting_rtcv_candidate", "no_rtcv_candidate"].includes(job.status)) {
        const retryLabel = job.status === "waiting_for_gpu" ? "Retry VLM" :
          (["queued_for_rtcv", "awaiting_rtcv_candidate", "no_rtcv_candidate"].includes(job.status) ? "Run RT-CV → VLM" : "Launch RT-CV → VLM");
        actions.append(button(retryLabel, () => launchJob(job), "primary"));
      }
      if (job.status === "completed" && !job.stored_asset_id) {
        actions.append(button("Save to Store", () => saveJob(job.job_id), "primary"));
      }
      if (job.status === "awaiting_rtcv_candidate") actions.append(node("span", "Waiting for RT-CV candidate", "ntc-vlm-warning"));
      if (job.status === "queued_for_rtcv") actions.append(node("span", "Queued · RT-CV will start automatically", "ntc-vlm-warning"));
      if (job.status === "running_rtcv") actions.append(node("span", "RT-CV is running on this upload", "ntc-vlm-warning"));
      if (job.status === "no_rtcv_candidate") actions.append(node("span", "No RT-CV candidate was detected", "ntc-vlm-warning"));
      if (job.status === "waiting_for_gpu") actions.append(node("span", "Waiting for local_vlm admission", "ntc-vlm-warning"));
      if (job.status === "completed" && job.stored_asset_id) actions.append(node("span", "Saved after VLM", "ntc-vlm-ok"));
      card.append(actions);
      jobs.append(card);
    });
    parent.append(jobs);
  }

  function renderUpload(parent) {
    const input = node("input");
    input.type = "file";
    input.multiple = true;
    input.accept = ".mp4,.mkv,video/mp4,video/x-matroska";
    input.hidden = true;
    input.addEventListener("change", () => {
      enqueueFiles(Array.from(input.files || []));
      input.value = "";
    });
    const drop = node("div", undefined, "ntc-vlm-drop");
    drop.append(node("strong", "Upload videos for RT-CV → VLM test"));
    drop.append(node("span", "Drag and drop MP4/MKV files here, or click to browse", "ntc-vlm-muted"));
    drop.append(input);
    drop.addEventListener("click", () => input.click());
    drop.addEventListener("dragover", (event) => { event.preventDefault(); drop.classList.add("drag"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("drag"));
    drop.addEventListener("drop", (event) => {
      event.preventDefault();
      drop.classList.remove("drag");
      enqueueFiles(Array.from(event.dataTransfer.files || []));
    });
    parent.append(drop);
    const next = node("article", undefined, "ntc-vlm-card");
    next.append(node("h3", "Sau khi upload"));
    next.append(node("p", "Video sẽ tự chạy RT-CV. Khi RT-CV tạo candidate, hệ thống tự tắt RT-CV, bật VLM và chạy tiếp; chỉ bấm Save to Store sau khi VLM hoàn tất.", "ntc-vlm-muted"));
    parent.append(next);
    if (state.files.length) {
      const list = node("div", undefined, "ntc-vlm-list");
      state.files.forEach((file, index) => {
        const row = node("div", undefined, "ntc-vlm-file");
        row.append(node("span", file.name));
        const progress = file.__ntcFailed ? file.__ntcError :
          (file.__ntcUploading ? `${(file.size / 1048576).toFixed(1)} MB · ${file.__ntcProgress || 0}%` : "Queued");
        row.append(node("span", progress, file.__ntcFailed ? "ntc-vlm-danger" : "ntc-vlm-muted"));
        if (file.__ntcFailed) {
          row.append(button("Retry", () => {
            file.__ntcFailed = false;
            file.__ntcError = "";
            processUploadQueue();
          }, "primary"));
        }
        row.append(button("×", () => { state.files.splice(index, 1); render(); }));
        list.append(row);
      });
      parent.append(list);
      const controls = node("div", undefined, "ntc-vlm-row");
      if (state.uploading) controls.append(node("span", "Uploading automatically…", "ntc-vlm-warning"));
      controls.append(button("+ Add More", () => input.click()));
      parent.append(controls);
    }
    parent.append(node("h3", "Recent tests"));
    renderJobs(parent);
  }

  function renderRealtime(parent) {
    parent.append(node("p", "Select a real RT-CV candidate. The selected clip is copied to VLM-test staging; it is not saved to Store until you explicitly Save after VLM.", "ntc-vlm-muted"));
    const list = node("div", undefined, "ntc-vlm-list");
    if (!state.candidates.length) list.append(node("p", "No eligible realtime candidates are available.", "ntc-vlm-muted"));
    state.candidates.forEach((candidate) => {
      const card = node("article", undefined, "ntc-vlm-card");
      card.append(node("h3", `${candidate.event_type || "candidate"} · ${candidate.camera_id || ""}`));
      card.append(node("p", `${candidate.start_time || ""} → ${candidate.end_time || ""}`, "ntc-vlm-muted"));
      card.append(button("Launch VLM test", () => launchRealtime(candidate.incident_id), "primary"));
      list.append(card);
    });
    parent.append(list);
  }

  function renderStore(parent) {
    parent.append(node("p", "Store contains only media explicitly saved after a completed VLM test. Launch runs VLM again without creating a new Store copy.", "ntc-vlm-muted"));
    const list = node("div", undefined, "ntc-vlm-list");
    if (!state.assets.length) list.append(node("p", "Store is empty.", "ntc-vlm-muted"));
    state.assets.forEach((asset) => {
      const card = node("article", undefined, "ntc-vlm-card");
      card.append(node("h3", asset.filename || asset.asset_id.slice(0, 12)));
      card.append(node("p", `${asset.camera_id} · ${asset.verdict || "VLM complete"} · ${asset.asset_id.slice(0, 12)}…`, "ntc-vlm-muted"));
      const video = node("video"); video.controls = true; video.preload = "metadata"; video.src = `${API}/store/${asset.asset_id}/media`; card.append(video);
      card.append(button("Launch VLM", () => launchStore(asset.asset_id), "primary"));
      list.append(card);
    });
    parent.append(list);
  }

  let drawer;
  function render() {
    if (!drawer) return;
    const body = drawer.querySelector(".ntc-vlm-body");
    body.replaceChildren();
    if (state.error) body.append(node("p", state.error, "ntc-vlm-status ntc-vlm-danger"));
    else body.append(node("p", "GPU-heavy work is admission-controlled and may remain queued.", "ntc-vlm-status"));
    if (state.tab === "upload") renderUpload(body);
    if (state.tab === "realtime") renderRealtime(body);
    if (state.tab === "store") renderStore(body);
    drawer.querySelectorAll(".ntc-vlm-tabs button").forEach((tab) => { tab.setAttribute("aria-selected", String(tab.dataset.tab === state.tab)); });
  }

  function init() {
    const style = node("style"); style.textContent = css; document.head.append(style);
    const launcher = button("VLM Test", () => { drawer.hidden = false; refresh(); });
    launcher.id = "ntc-vlm-test-launcher";
    launcher.setAttribute("aria-label", "Open VLM Test");
    launcher.title = "VLM Test";
    // Keep the launcher outside React-owned nodes. React re-renders the VSS
    // header/sidebar and removes children that were injected into its tree.
    // A body-level control also remains available while the Chat drawer is open.
    document.body.append(launcher);
    drawer = node("aside"); drawer.id = "ntc-vlm-test-drawer"; drawer.hidden = true;
    const head = node("header", undefined, "ntc-vlm-head");
    const heading = node("div"); heading.append(node("h2", "VLM Test")); heading.append(node("small", "NVIDIA VSS-style video workflow")); head.append(heading);
    head.append(button("×", () => { drawer.hidden = true; })); drawer.append(head);
    const tabs = node("nav", undefined, "ntc-vlm-tabs");
    [["upload", "Upload"], ["realtime", "Realtime"], ["store", "Store"]].forEach(([key, label]) => { const tab = button(label, () => { state.tab = key; render(); refresh(); }); tab.dataset.tab = key; tab.setAttribute("aria-selected", String(key === state.tab)); tabs.append(tab); });
    drawer.append(tabs); drawer.append(node("main", undefined, "ntc-vlm-body"));
    const footer = node("footer", undefined, "ntc-vlm-footer"); footer.append(button("Refresh", refresh)); footer.append(button("Close", () => { drawer.hidden = true; })); drawer.append(footer);
    document.body.append(drawer); render();
    window.setInterval(() => { if (!drawer.hidden) refresh(); }, 5000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
