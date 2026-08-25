const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = { runs: [], selectedId: null, selected: null, compareIds: [], bulkMode: false, deleteIds: [], view: "observe", poller: null, loading: false, tokenPoint: null, reports: [], selectedReportId: null };
const statusLabel = { queued: "排队", running: "运行中", completed: "已完成", failed: "失败", cancelled: "已取消" };

function esc(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

function fmt(value, digits = 1) {
  return value == null || Number.isNaN(Number(value)) ? "—" : Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function createSuiteId() {
  const webCrypto = globalThis.crypto;
  if (webCrypto?.randomUUID) return webCrypto.randomUUID().replace(/-/g, "").slice(0, 20);
  if (webCrypto?.getRandomValues) {
    const bytes = new Uint8Array(16);
    webCrypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    return [...bytes].map(byte => byte.toString(16).padStart(2, "0")).join("").slice(0, 20);
  }
  return `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`.slice(0, 20);
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(node.timer);
  node.timer = setTimeout(() => node.classList.remove("show"), 2800);
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || body);
    } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

async function checkHealth() {
  try {
    const health = await api("/api/health");
    $("#healthDot").classList.add("online");
    $("#healthText").textContent = "本地在线";
    $("#dataPath").textContent = health.data_path;
  } catch (_) {
    $("#healthDot").classList.remove("online");
    $("#healthText").textContent = "连接断开";
  }
}

function updateClock() {
  $("#clock").textContent = new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date()) + " CST";
}

async function loadRuns(keepSelection = true) {
  if (state.loading) return;
  state.loading = true;
  try {
    state.runs = await api("/api/runs");
    await loadReports(true);
    $("#runCount").textContent = state.runs.length;
    const running = state.runs.find(item => item.run.status === "running");
    const selected = keepSelection && state.selectedId
      ? state.runs.find(item => item.run.id === state.selectedId)
      : null;
    // Follow the active queue when the previously selected run has finished.
    // This keeps the detail panel useful during a matrix run without changing
    // the selection when there is no other active task to follow.
    const current = selected && (!running || ["queued", "running"].includes(selected.run.status))
      ? selected
      : running || selected || state.runs[0];
    if (current) await selectRun(current.run.id, false);
    else { renderHistory(); renderEmpty(); }
  } catch (error) { toast(`读取记录失败：${error.message}`); }
  finally {
    state.loading = false;
    managePolling();
  }
}

async function loadReports(keepSelection = true) {
  state.reports = await api("/api/reports");
  $("#reportCount").textContent = state.reports.length;
  const selected = keepSelection && state.selectedReportId
    ? state.reports.find(report => report.id === state.selectedReportId)
    : null;
  state.selectedReportId = (selected || state.reports[0])?.id || null;
  renderReportPicker();
  renderReport();
}

function renderReportPicker() {
  const picker = $("#reportSelect");
  picker.disabled = !state.reports.length;
  picker.innerHTML = state.reports.length
    ? state.reports.map(report => `<option value="${esc(report.id)}" ${report.id === state.selectedReportId ? "selected" : ""}>${esc(report.title)}</option>`).join("")
    : `<option value="">暂无报告</option>`;
  ["#reportSettingsBtn", "#regenerateReportBtn", "#copyReportBtn", "#exportReportJsonBtn", "#exportReportHtmlBtn", "#printReportBtn"].forEach(selector => {
    $(selector).disabled = !state.selectedReportId;
  });
}

function reportLineChart(levels, series, unit) {
  const width=720, height=250, pad={l:58,r:22,t:24,b:42};
  const values=series.flatMap(item=>levels.map(level=>Number(item.value(level))).filter(Number.isFinite));
  const max=Math.max(...values,1), min=Math.min(...values,0), span=Math.max(max-min,1);
  const x=index=>pad.l+(levels.length===1?0:(width-pad.l-pad.r)*index/(levels.length-1));
  const y=value=>pad.t+(height-pad.t-pad.b)*(1-(value-min)/span);
  const grid=[0,.5,1].map(ratio=>{const value=max-(max-min)*ratio, yy=pad.t+(height-pad.t-pad.b)*ratio;return `<line x1="${pad.l}" y1="${yy}" x2="${width-pad.r}" y2="${yy}"/><text x="${pad.l-9}" y="${yy+4}" text-anchor="end">${fmt(value,0)}</text>`;}).join("");
  const lines=series.map(item=>{
    const points=levels.map((level,index)=>`${x(index)},${y(Number(item.value(level))||0)}`).join(" ");
    const dots=levels.map((level,index)=>`<circle cx="${x(index)}" cy="${y(Number(item.value(level))||0)}" r="4"><title>C${level.concurrency} · ${item.label} ${fmt(item.value(level),1)} ${unit}</title></circle>`).join("");
    return `<g class="report-series" style="--series:${item.color}"><polyline points="${points}"/>${dots}</g>`;
  }).join("");
  const labels=levels.map((level,index)=>`<text x="${x(index)}" y="${height-12}" text-anchor="middle">C${level.concurrency}</text>`).join("");
  const legend=series.map(item=>`<span><i style="background:${item.color}"></i>${esc(item.label)}</span>`).join("");
  return `<div class="report-chart-legend">${legend}</div><svg class="report-line-chart" viewBox="0 0 ${width} ${height}" role="img">${grid}${lines}${labels}</svg>`;
}

function stabilityChart(levels) {
  const max=Math.max(...levels.map(level=>Number(level.stability.throughput_cv_pct)||0),10);
  return `<div class="stability-bars">${levels.map(level=>{
    const value=Number(level.stability.throughput_cv_pct)||0;
    return `<div><span>C${level.concurrency}</span><i><b style="width:${Math.min(100,value/max*100)}%"></b></i><strong>${fmt(level.stability.throughput_cv_pct,2)}%</strong></div>`;
  }).join("")}</div>`;
}

function renderReport() {
  const report=state.reports.find(item=>item.id===state.selectedReportId);
  $("#reportEmpty").classList.toggle("hidden", Boolean(report));
  const paper=$("#reportCapture");
  paper.classList.toggle("hidden", !report);
  if(!report) return;
  const snapshot=report.snapshot, levels=snapshot.levels || [], headline=snapshot.headline, recommended=headline.recommended || {};
  const quality=snapshot.quality || {}, suite=snapshot.suite || {}, criteria=report.criteria || {}, environment=report.environment || {};
  const configuredCriteria=Object.entries(criteria).filter(([,value])=>value!=null);
  const criteriaLabels={min_success_rate:"成功率 ≥",min_output_throughput_tps:"吞吐 ≥",max_ttft_p95_ms:"TTFT P95 ≤",max_latency_p95_ms:"Latency P95 ≤"};
  paper.innerHTML=`
    <header class="report-cover">
      <div><span class="report-kicker">INFERBENCH / LOCAL EVIDENCE / ${esc(report.analysis_version)}</span><h1>${esc(report.title)}</h1><p>${esc(suite.framework)} · ${esc(suite.model)} · ${esc(suite.endpoint)}</p></div>
      <div class="quality-seal"><strong>${esc(quality.grade || "—")}</strong><span>证据等级</span><small>${esc(quality.label || "")}</small></div>
    </header>
    <div class="report-meta"><span>生成 ${new Date(report.updated_at*1000).toLocaleString("zh-CN",{hour12:false})}</span><span>${suite.run_count} runs · ${suite.repetitions} 轮/档</span><span>${suite.requests_per_run} 请求/轮 · max ${suite.max_tokens} tokens</span><span>分析版本 ${esc(report.analysis_version)}</span></div>
    <section class="report-verdict">
      <div><span>RECOMMENDED OPERATING POINT</span><h2>C${headline.recommended_concurrency}</h2><p>推荐并发</p></div>
      <dl><div><dt>平均输出吞吐</dt><dd>${fmt(recommended.output_throughput_tps)} <small>tok/s</small></dd></div><div><dt>Latency P95</dt><dd>${fmt(recommended.latency_ms?.p95,0)} <small>ms</small></dd></div><div><dt>TTFT P95</dt><dd>${fmt(recommended.ttft_ms?.p95,0)} <small>ms</small></dd></div><div><dt>成功率</dt><dd>${fmt(recommended.success_rate,2)}<small>%</small></dd></div></dl>
      <div class="saturation-note ${snapshot.saturation.detected?"warning":""}"><span>${snapshot.saturation.detected?"SATURATION FOUND":"HEADROOM"}</span><strong>${snapshot.saturation.detected?`C${snapshot.saturation.concurrency} 出现拐点`:"测试范围内仍有扩展空间"}</strong><p>${esc(snapshot.saturation.reason || "建议增加更高并发档继续验证服务上限。")}</p></div>
    </section>
    <section class="report-conclusions"><header><span>EXECUTIVE FINDINGS</span><h2>结论摘要</h2></header><div>${snapshot.conclusions.map((item,index)=>`<article class="${esc(item.tone)}"><b>${String(index+1).padStart(2,"0")}</b><div><h3>${esc(item.title)}</h3><p>${esc(item.body)}</p></div></article>`).join("")}</div></section>
    ${quality.warnings?.length?`<section class="report-quality-warning"><strong>数据质量提示</strong><ul>${quality.warnings.map(item=>`<li>${esc(item)}</li>`).join("")}</ul></section>`:""}
    <section class="report-chart-grid">
      <article><header><span>SCALING CURVE</span><h3>Token 吞吐随并发变化</h3></header>${reportLineChart(levels,[{label:"Output tok/s",color:"#315cf5",value:level=>level.summary.output_throughput_tps}],"tok/s")}</article>
      <article><header><span>TAIL LATENCY</span><h3>响应延迟与首 Token</h3></header>${reportLineChart(levels,[{label:"Latency P95",color:"#e88b3d",value:level=>level.summary.latency_ms?.p95},{label:"TTFT P95",color:"#7657e8",value:level=>level.summary.ttft_ms?.p95}],"ms")}</article>
      <article><header><span>REPEATABILITY</span><h3>三轮吞吐稳定性 · CV</h3></header>${stabilityChart(levels)}<p class="report-method">CV 越低越稳定；≤5% 通常表示测试重复性良好。</p></article>
      <article><header><span>REQUEST OUTCOME</span><h3>成功与错误分布</h3></header><div class="outcome-visual"><div class="outcome-ring" style="--success:${recommended.success_rate||0}"><strong>${fmt(recommended.success_rate,2)}%</strong><span>推荐档成功率</span></div><div><b>${quality.sample_count||0}</b><span>总样本</span><b>${snapshot.errors.reduce((sum,item)=>sum+item.count,0)}</b><span>失败请求</span></div></div></article>
    </section>
    <section class="report-table-section"><header><span>CONCURRENCY MATRIX</span><h2>并发档评估明细</h2></header><div class="comparison-table"><table><thead><tr><th>并发</th><th>轮次</th><th>Output tok/s</th><th>吞吐增益</th><th>吞吐 CV</th><th>TTFT P95</th><th>Latency P95</th><th>成功率</th><th>判定</th></tr></thead><tbody>${levels.map(level=>`<tr class="${level.concurrency===headline.recommended_concurrency?"recommended-row":""}"><td><strong>C${level.concurrency}</strong></td><td>${level.repetitions}</td><td>${fmt(level.summary.output_throughput_tps)}</td><td>${delta(level.changes.throughput_pct)}</td><td>${fmt(level.stability.throughput_cv_pct,2)}%</td><td>${fmt(level.summary.ttft_ms?.p95,0)} ms</td><td>${fmt(level.summary.latency_ms?.p95,0)} ms</td><td>${fmt(level.summary.success_rate,2)}%</td><td>${level.concurrency===headline.recommended_concurrency?"推荐":level.meets_criteria?"通过":"未达标"}</td></tr>`).join("")}</tbody></table></div></section>
    <footer class="report-foot"><div><span>评估标准</span><p>${configuredCriteria.length?configuredCriteria.map(([key,value])=>`${criteriaLabels[key]} ${fmt(value)}${key.includes("rate")?"%":key.includes("throughput")?" tok/s":" ms"}`).join(" · "):"未配置硬性 SLO，采用内置平衡规则"}</p></div><div><span>运行环境</span><p>${Object.values(environment).filter(Boolean).length?Object.entries(environment).filter(([,value])=>value).map(([key,value])=>`${esc(key)}: ${esc(value)}`).join(" · "):"未补充硬件与框架版本"}</p></div><small>本报告由本地确定性规则生成 · 快照不会随原始数据自动漂移 · ${esc(report.id)}</small></footer>`;
}

function progressOf(item) {
  const target = item.run.config.requests || 1;
  return Math.min(100, item.run.completed_requests / target * 100);
}

function renderHistory() {
  const list = $("#historyList");
  if (!state.runs.length) {
    list.innerHTML = `<div class="history-empty">尚无本地实验记录。运行一次 mock 压测后，这里会保留可比较的历史。</div>`;
    syncCompareButton();
    syncBulkControls();
    return;
  }
  const deletableIds = new Set(state.runs.filter(item => !["queued","running"].includes(item.run.status)).map(item => item.run.id));
  state.deleteIds = state.deleteIds.filter(id => deletableIds.has(id));
  const activeOrder = state.runs
    .filter(item => ["queued","running"].includes(item.run.status))
    .sort((a,b) => a.run.created_at - b.run.created_at);
  const queuePositions = new Map(activeOrder.map((item,index) => [item.run.id,index + 1]));
  list.innerHTML = state.runs.map(item => {
    const run = item.run, summary = item.summary;
    const checked = state.compareIds.includes(run.id);
    const deleteChecked = state.deleteIds.includes(run.id);
    const deleteLocked = ["queued","running"].includes(run.status);
    const statusText = run.status === "queued"
      ? `排队 #${queuePositions.get(run.id) || "—"}/${activeOrder.length}`
      : statusLabel[run.status] || run.status;
    const selector = state.bulkMode
      ? `<button class="compare-check bulk-check ${deleteChecked ? "checked" : ""}" type="button" data-delete-id="${esc(run.id)}" aria-label="选择删除 ${esc(run.name)}" ${deleteLocked ? "disabled" : ""}>${deleteChecked ? "✓" : ""}</button>`
      : `<button class="compare-check ${checked ? "checked" : ""}" type="button" data-check-id="${esc(run.id)}" aria-label="加入对比">${checked ? "✓" : ""}</button>`;
    return `<article class="history-item ${run.id === state.selectedId && !state.bulkMode ? "active" : ""} ${deleteChecked ? "bulk-selected" : ""} ${state.bulkMode && deleteLocked ? "bulk-locked" : ""}" data-run-id="${esc(run.id)}">
      ${selector}
      <div class="history-copy"><strong>${esc(run.name)}</strong><span>${esc(run.framework)} · ${esc(run.model)} · ${new Date(run.created_at * 1000).toLocaleString("zh-CN", {month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"})}</span>
        <div class="history-metrics"><span>${statusText}</span><span><b>${fmt(summary.output_throughput_tps)}</b> tok/s</span><span>${fmt(summary.latency_ms.p95,0)} ms P95</span></div>
      </div>
      ${["running","queued"].includes(run.status) ? `<div class="mini-progress"><i style="width:${progressOf(item)}%"></i></div>` : ""}
    </article>`;
  }).join("");

  $$("[data-run-id]").forEach(node => node.addEventListener("click", event => {
    if (event.target.closest("[data-check-id], [data-delete-id]")) return;
    if (state.bulkMode) return toggleDeleteSelection(node.dataset.runId);
    selectRun(node.dataset.runId);
  }));
  $$("[data-check-id]").forEach(button => button.addEventListener("click", () => toggleCompare(button.dataset.checkId)));
  $$("[data-delete-id]").forEach(button => button.addEventListener("click", () => toggleDeleteSelection(button.dataset.deleteId)));
  syncCompareButton();
  syncBulkControls();
}

function toggleDeleteSelection(id) {
  const item = state.runs.find(candidate => candidate.run.id === id);
  if (!item || ["queued","running"].includes(item.run.status)) return toast("运行中或排队中的实验不能直接删除");
  const at = state.deleteIds.indexOf(id);
  if (at >= 0) state.deleteIds.splice(at, 1);
  else state.deleteIds.push(id);
  renderHistory();
}

function syncBulkControls() {
  const bar = $("#bulkDeleteBar"), modeButton = $("#bulkModeBtn"), deleteButton = $("#bulkDeleteBtn"), selectAllButton = $("#bulkSelectAllBtn");
  bar.classList.toggle("hidden", !state.bulkMode);
  modeButton.classList.toggle("active", state.bulkMode);
  modeButton.textContent = state.bulkMode ? "完成" : "多选";
  $("#bulkSelectedCount").textContent = state.deleteIds.length;
  deleteButton.disabled = state.deleteIds.length === 0;
  const deletable = state.runs.filter(item => !["queued","running"].includes(item.run.status)).map(item => item.run.id);
  selectAllButton.disabled = deletable.length === 0;
  selectAllButton.textContent = deletable.length && deletable.every(id => state.deleteIds.includes(id)) ? "取消全选" : "全选";
}

function toggleCompare(id) {
  const at = state.compareIds.indexOf(id);
  if (at >= 0) state.compareIds.splice(at, 1);
  else if (state.compareIds.length < 64) state.compareIds.push(id);
  else return toast("一次最多对比 64 个实验");
  syncCompareButton();
  renderHistory();
}

function syncCompareButton() {
  $("#compareCount").textContent = state.compareIds.length;
  const button=$("#compareBtn"), selected=state.runs.filter(item=>state.compareIds.includes(item.run.id));
  const pending=selected.filter(item=>["queued","running"].includes(item.run.status)).length;
  button.disabled=state.compareIds.length<2 || pending>0;
  button.textContent=state.compareIds.length<2 ? "选择至少 2 个实验" : pending ? `等待 ${pending} 轮完成` : `汇总对比 ${state.compareIds.length} 轮`;
}

async function selectRun(id, switchView = true) {
  if (state.selectedId !== id) state.tokenPoint = null;
  state.selectedId = id;
  try {
    const cached = state.runs.find(item => item.run.id === id);
    state.selected = cached?.run.status === "queued"
      ? { ...cached, samples: [] }
      : await api(`/api/runs/${encodeURIComponent(id)}`);
    renderDetail(state.selected);
    renderHistory();
    if (switchView) setView("observe");
  } catch (error) { toast(`读取实验失败：${error.message}`); }
}

function renderEmpty() {
  state.selectedId = null;
  state.selected = null;
  $("#emptyState").classList.remove("hidden");
  $("#detailView").classList.add("hidden");
}

function metric(label, value, unit, note) {
  return `<article class="metric"><span>${label}</span><strong>${value}${unit ? `<small> ${unit}</small>` : ""}</strong><small>${note}</small></article>`;
}

function renderDetail(item) {
  const { run, summary, samples } = item;
  $("#emptyState").classList.add("hidden");
  $("#detailView").classList.remove("hidden");
  $("#runEyebrow").textContent = `RUN / ${run.id}`;
  $("#runTitle").textContent = run.name;
  $("#runSubtitle").textContent = `${run.framework.toUpperCase()} · ${run.model} · C${run.config.concurrency} / N${run.config.requests} · ${run.endpoint}`;
  const chip = $("#runStatus");
  chip.textContent = statusLabel[run.status] || run.status;
  chip.className = `status-chip ${run.status}`;
  $("#progressBar").style.width = `${progressOf(item)}%`;
  const notice = $("#queueNotice");
  if (run.status === "queued") {
    const activeOrder = state.runs
      .filter(candidate => ["queued","running"].includes(candidate.run.status))
      .sort((a,b) => a.run.created_at - b.run.created_at);
    const position = activeOrder.findIndex(candidate => candidate.run.id === run.id);
    const running = activeOrder.find(candidate => candidate.run.status === "running");
    const runningProgress = running ? `${running.run.completed_requests}/${running.run.config.requests}` : "准备中";
    notice.innerHTML = `<div><strong>当前实验尚未开始</strong><br>队列位置 ${position + 1}/${activeOrder.length}，前面还有 ${Math.max(position,0)} 轮。${running ? `正在运行「${esc(running.run.name)}」(${runningProgress})。` : "Runner 正在准备下一轮。"}</div>${running ? `<button id="viewRunningBtn" type="button">查看当前运行</button>` : ""}`;
    notice.classList.remove("hidden");
    $("#viewRunningBtn")?.addEventListener("click", () => selectRun(running.run.id));
  } else {
    notice.classList.add("hidden");
    notice.innerHTML = "";
  }
  $("#cancelBtn").classList.toggle("hidden", !["queued","running"].includes(run.status));
  $("#cancelSuiteBtn").classList.toggle("hidden", !run.config.suite_id || !["queued","running"].includes(run.status));
  const suiteReport=run.config.suite_id ? state.reports.find(report=>report.suite_id===run.config.suite_id) : null;
  const suiteRuns=run.config.suite_id ? state.runs.filter(candidate=>candidate.run.config.suite_id===run.config.suite_id) : [];
  const suiteTerminal=suiteRuns.length && suiteRuns.every(candidate=>["completed","failed","cancelled"].includes(candidate.run.status));
  $("#viewReportBtn").classList.toggle("hidden", !run.config.suite_id || (!suiteReport && !suiteTerminal));
  $("#viewReportBtn").textContent=suiteReport?"查看报告":"生成报告";
  $("#deleteBtn").classList.toggle("hidden", ["queued","running"].includes(run.status));
  $("#copyScreenshotBtn").disabled = false;
  $("#exportCsvBtn").disabled = !samples.length;
  $("#exportJsonBtn").disabled = !samples.length;
  $("#metricGrid").innerHTML = [
    metric("OUTPUT THROUGHPUT", fmt(summary.output_throughput_tps), "tok/s", `${fmt(summary.request_throughput_rps,2)} request/s`),
    metric("TTFT / P50", fmt(summary.ttft_ms.p50), "ms", `P95 ${fmt(summary.ttft_ms.p95)} ms`),
    metric("LATENCY / P95", fmt(summary.latency_ms.p95), "ms", `P50 ${fmt(summary.latency_ms.p50)} ms`),
    metric("SUCCESS RATE", fmt(summary.success_rate,2), "%", `${summary.successful} ok · ${summary.failed} failed`),
  ].join("");
  const emptyMessage = run.status === "queued" ? "排队中 · 轮到后开始采样" : "等待首批样本…";
  drawHistogram(samples.filter(x => x.ok).map(x => x.latency_ms), emptyMessage);
  drawTimeline(samples, emptyMessage);
  drawTokenSpeed(samples, summary.output_throughput_tps, emptyMessage);
  $("#sampleRows").innerHTML = samples.slice().reverse().slice(0, 150).map(sample => `<tr>
    <td>${sample.request_index}</td><td class="${sample.ok ? "ok-pill" : "fail-pill"}">${sample.ok ? "● OK" : "● FAIL"}</td>
    <td>${fmt(sample.ttft_ms)} ms</td><td>${fmt(sample.latency_ms)} ms</td><td>${sample.input_tokens} → ${sample.output_tokens}</td>
    <td>${sample.token_source === "usage" ? "usage" : "~ estimated"}</td><td title="${esc(sample.error)}">${esc(sample.error || "—")}</td>
  </tr>`).join("") || `<tr><td colspan="7">${run.status === "queued" ? "排队中，轮到后开始采样…" : "等待首批样本…"}</td></tr>`;
}

function drawHistogram(values, emptyMessage = "等待首批样本…") {
  const node = $("#histogram");
  if (!values.length) return node.innerHTML = `<div class="chart-empty">${esc(emptyMessage)}</div>`;
  const buckets = Math.min(12, Math.max(5, Math.ceil(Math.sqrt(values.length))));
  const min = Math.min(...values), max = Math.max(...values), span = Math.max(max - min, 1);
  const counts = Array(buckets).fill(0);
  values.forEach(value => counts[Math.min(buckets - 1, Math.floor((value - min) / span * buckets))]++);
  const peak = Math.max(...counts), width = 520, height = 180, pad = {l:30,r:8,t:12,b:25}, innerW = width-pad.l-pad.r, innerH=height-pad.t-pad.b;
  const gap = 4, barW = innerW / buckets - gap;
  const bars = counts.map((count,index) => {
    const h = count / peak * innerH, x=pad.l + index * innerW/buckets, y=pad.t+innerH-h;
    return `<rect class="bar" x="${x}" y="${y}" width="${barW}" height="${h}"><title>${count} requests</title></rect>`;
  }).join("");
  node.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="Latency histogram"><line class="axis" x1="${pad.l}" y1="${pad.t+innerH}" x2="${width-pad.r}" y2="${pad.t+innerH}"/>${bars}<text x="${pad.l}" y="${height-5}">${fmt(min,0)} ms</text><text x="${width-pad.r}" y="${height-5}" text-anchor="end">${fmt(max,0)} ms</text></svg>`;
}

function drawTimeline(samples, emptyMessage = "等待首批样本…") {
  const node = $("#timeline");
  if (!samples.length) return node.innerHTML = `<div class="chart-empty">${esc(emptyMessage)}</div>`;
  const width=400,height=180,pad={l:34,r:9,t:12,b:25};
  const maxX=Math.max(...samples.map(x=>x.started_offset_ms),1), maxY=Math.max(...samples.map(x=>x.latency_ms),1);
  const dots=samples.map(sample => {
    const x=pad.l+sample.started_offset_ms/maxX*(width-pad.l-pad.r), y=pad.t+(1-sample.latency_ms/maxY)*(height-pad.t-pad.b);
    return `<circle class="dot ${sample.ok ? "" : "fail"}" cx="${x}" cy="${y}" r="3"><title>#${sample.request_index}: ${fmt(sample.latency_ms)} ms</title></circle>`;
  }).join("");
  node.innerHTML=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Request timeline"><line class="axis" x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${height-pad.b}"/><line class="axis" x1="${pad.l}" y1="${height-pad.b}" x2="${width-pad.r}" y2="${height-pad.b}"/>${dots}<text x="4" y="${pad.t+4}">${fmt(maxY,0)}</text><text x="${width-pad.r}" y="${height-5}" text-anchor="end">${fmt(maxX/1000,1)} s</text></svg>`;
}

function buildTokenSpeedSeries(samples) {
  const intervals = samples.filter(sample => sample.ok && Number(sample.output_tokens) > 0).map(sample => {
    const requestStart = Math.max(0, Number(sample.started_offset_ms) || 0);
    const latency = Math.max(1, Number(sample.latency_ms) || 1);
    const ttft = sample.ttft_ms == null ? 0 : Math.max(0, Number(sample.ttft_ms) || 0);
    const start = requestStart + Math.min(ttft, latency - 1);
    const end = Math.max(start + 1, requestStart + latency);
    return { start, end, duration: end - start, tokens: Number(sample.output_tokens) };
  });
  if (!intervals.length) return { points: [], bucketMs: 0, durationMs: 0 };

  const durationMs = Math.max(...intervals.map(interval => interval.end), 1);
  const targetBucketMs = durationMs / 48;
  const bucketChoices = [100, 250, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000];
  const bucketMs = bucketChoices.find(value => value >= targetBucketMs) || Math.ceil(targetBucketMs / 60000) * 60000;
  const bucketCount = Math.max(2, Math.ceil(durationMs / bucketMs));
  const points = Array.from({ length: bucketCount }, (_, index) => {
    const bucketStart = index * bucketMs;
    const bucketEnd = Math.min((index + 1) * bucketMs, durationMs);
    const windowMs = Math.max(bucketEnd - bucketStart, 1);
    const tokens = intervals.reduce((total, interval) => {
      const overlap = Math.max(0, Math.min(interval.end, bucketEnd) - Math.max(interval.start, bucketStart));
      return total + interval.tokens * overlap / interval.duration;
    }, 0);
    return { timeMs: bucketStart + windowMs / 2, speed: tokens / (windowMs / 1000) };
  });
  return { points, bucketMs, durationMs };
}

function drawTokenSpeed(samples, averageThroughput, emptyMessage = "等待首批样本…") {
  const node = $("#tokenSpeedChart"), meta = $("#tokenSpeedMeta");
  const { points, bucketMs, durationMs } = buildTokenSpeedSeries(samples);
  if (!points.length) {
    meta.textContent = "—";
    node.innerHTML = `<div class="chart-empty">${esc(emptyMessage)}</div>`;
    return;
  }

  const average = Math.max(0, Number(averageThroughput) || 0);
  const peak = Math.max(...points.map(point => point.speed), average, 1);
  const maxY = peak * 1.12;
  const width = 900, height = 220, pad = { l: 47, r: 18, t: 14, b: 30 };
  const innerW = width - pad.l - pad.r, innerH = height - pad.t - pad.b;
  const x = timeMs => pad.l + timeMs / Math.max(durationMs, 1) * innerW;
  const y = speed => pad.t + (1 - speed / maxY) * innerH;
  const coordinates = points.map(point => ({ ...point, x: x(point.timeMs), y: y(point.speed) }));
  const linePath = coordinates.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
  const baselineY = pad.t + innerH;
  const areaPath = `${linePath} L${coordinates.at(-1).x.toFixed(2)},${baselineY} L${coordinates[0].x.toFixed(2)},${baselineY} Z`;
  const horizontalGrid = [0, .25, .5, .75, 1].map(ratio => {
    const gridY = pad.t + (1 - ratio) * innerH;
    return `<line class="grid-line" x1="${pad.l}" y1="${gridY}" x2="${width-pad.r}" y2="${gridY}"/><text x="${pad.l-7}" y="${gridY+3}" text-anchor="end">${fmt(maxY*ratio,0)}</text>`;
  }).join("");
  const pointNodes = coordinates.map(point => `<circle class="token-point" cx="${point.x}" cy="${point.y}" r="3.2" tabindex="0" role="button" data-time-ms="${point.timeMs}" data-speed="${point.speed}" aria-label="压测第 ${fmt(point.timeMs/1000,1)} 秒，${fmt(point.speed,1)} tok/s"><title>${fmt(point.timeMs/1000,1)}s · ${fmt(point.speed,1)} tok/s</title></circle>`).join("");
  const averageLine = average > 0
    ? `<line class="average-line" x1="${pad.l}" y1="${y(average)}" x2="${width-pad.r}" y2="${y(average)}"/><text class="average-label" x="${width-pad.r-2}" y="${Math.max(pad.t+9,y(average)-5)}" text-anchor="end">AVG ${fmt(average,1)}</text>`
    : "";
  const bucketLabel = bucketMs >= 1000 ? `${fmt(bucketMs/1000,1)}s` : `${bucketMs}ms`;
  meta.textContent = `峰值 ${fmt(peak,1)} · ${bucketLabel} 窗口`;
  node.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Token throughput over time">
    <defs><linearGradient id="tokenAreaGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#159a74" stop-opacity=".24"/><stop offset="100%" stop-color="#159a74" stop-opacity=".02"/></linearGradient></defs>
    ${horizontalGrid}<line class="axis" x1="${pad.l}" y1="${baselineY}" x2="${width-pad.r}" y2="${baselineY}"/>
    <path class="token-area" d="${areaPath}"/><path class="token-line" d="${linePath}"/>${averageLine}${pointNodes}
    <text x="${pad.l}" y="${height-6}">0s</text><text x="${pad.l+innerW/2}" y="${height-6}" text-anchor="middle">${fmt(durationMs/2000,1)}s</text><text x="${width-pad.r}" y="${height-6}" text-anchor="end">${fmt(durationMs/1000,1)}s</text>
  </svg><div class="token-speed-tooltip hidden" role="status" aria-live="polite"></div>`;

  const tooltip = node.querySelector(".token-speed-tooltip");
  const circles = [...node.querySelectorAll(".token-point")];
  let pinned = false;
  const hideTooltip = () => {
    tooltip.classList.add("hidden");
    tooltip.classList.remove("below");
    circles.forEach(circle => circle.classList.remove("selected"));
  };
  const showTooltip = (circle, persist = false) => {
    const speed = Number(circle.dataset.speed), timeMs = Number(circle.dataset.timeMs);
    const nodeRect = node.getBoundingClientRect(), circleRect = circle.getBoundingClientRect();
    const pointX = circleRect.left - nodeRect.left + circleRect.width / 2;
    const pointY = circleRect.top - nodeRect.top + circleRect.height / 2;
    const below = pointY < 58;
    tooltip.innerHTML = `<strong>${fmt(speed,1)} tok/s</strong><span>压测第 ${fmt(timeMs/1000,1)} 秒</span>`;
    tooltip.style.left = `${Math.min(Math.max(pointX,72),node.clientWidth-72)}px`;
    tooltip.style.top = `${below ? pointY+12 : pointY-10}px`;
    tooltip.classList.toggle("below", below);
    tooltip.classList.remove("hidden");
    circles.forEach(item => item.classList.toggle("selected", item === circle && persist));
    pinned = persist;
    if (persist) state.tokenPoint = { runId: state.selectedId, timeMs };
  };

  circles.forEach(circle => {
    circle.addEventListener("pointerenter", () => { if (!pinned) showTooltip(circle); });
    circle.addEventListener("pointerleave", () => { if (!pinned) hideTooltip(); });
    circle.addEventListener("focus", () => { if (!pinned) showTooltip(circle); });
    circle.addEventListener("blur", () => { if (!pinned) hideTooltip(); });
    circle.addEventListener("click", event => {
      event.stopPropagation();
      showTooltip(circle, true);
    });
    circle.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        showTooltip(circle, true);
      }
    });
  });
  node.addEventListener("click", event => {
    if (event.target.closest(".token-point")) return;
    pinned = false;
    state.tokenPoint = null;
    hideTooltip();
  });

  if (state.tokenPoint?.runId === state.selectedId && circles.length) {
    const restored = circles.reduce((best, circle) =>
      Math.abs(Number(circle.dataset.timeMs)-state.tokenPoint.timeMs) < Math.abs(Number(best.dataset.timeMs)-state.tokenPoint.timeMs) ? circle : best
    );
    showTooltip(restored, true);
  }
}

function managePolling() {
  const hasActive = state.runs.some(item => ["queued","running"].includes(item.run.status));
  if ((!hasActive || document.visibilityState !== "visible") && state.poller) {
    clearTimeout(state.poller);
    state.poller = null;
  }
  if (hasActive && !state.poller && document.visibilityState === "visible") {
    state.poller = setTimeout(async () => {
      state.poller = null;
      await loadRuns(true);
    }, 1500);
  }
}

function setView(view) {
  state.view = view;
  $$(".view-tab").forEach(tab => tab.classList.toggle("active", tab.dataset.view === view));
  $("#observeView").classList.toggle("active", view === "observe");
  $("#compareView").classList.toggle("active", view === "compare");
  $("#reportView").classList.toggle("active", view === "report");
}

async function runCompare() {
  if (state.compareIds.length < 2) return;
  try {
    const result = await api(`/api/compare?aggregate=true&ids=${encodeURIComponent(state.compareIds.join(","))}`);
    $("#compareWarnings").innerHTML = result.warnings.length ? `<div class="warning-box"><strong>可比性提醒：</strong> ${result.warnings.map(esc).join("；")}</div>` : "";
    $("#compareResults").innerHTML = result.items.map((item,index) => `<article class="ranking-card">
      <div class="rank">${String(index+1).padStart(2,"0")}</div><div class="rank-name"><strong>${esc(item.run.name)}</strong><small>${esc(item.run.framework)} · ${esc(item.run.model)} ${item.run.id===result.baseline_id?"· BASELINE":""}${item.repeat_aggregation?` · ${item.repeat_aggregation.runs} RUN MEAN`:""}</small></div>
      <div class="score-track"><i style="width:${item.score}%"></i></div><div class="score">${fmt(item.score,1)}<small>SCORE / 100</small></div>
    </article>`).join("") + `<div class="comparison-table"><table><thead><tr><th>实验</th><th>Output tok/s</th><th>吞吐 CV</th><th>vs baseline</th><th>TTFT P50</th><th>Latency P95</th><th>成功率</th></tr></thead><tbody>${result.items.map(item=>`<tr><td>${esc(item.run.name)}</td><td>${fmt(item.summary.output_throughput_tps)}</td><td>${item.repeat_aggregation?fmt(item.repeat_aggregation.output_throughput_cv_pct,2)+"%":"—"}</td><td>${delta(item.vs_baseline_pct.output_throughput_tps)}</td><td>${fmt(item.summary.ttft_ms.p50)} ms</td><td>${fmt(item.summary.latency_ms.p95)} ms</td><td>${fmt(item.summary.success_rate,2)}%</td></tr>`).join("")}</tbody></table></div>`;
  } catch (error) { toast(`对比失败：${error.message}`); }
}

function delta(value) { return value == null ? "—" : `${value > 0 ? "+" : ""}${fmt(value,2)}%`; }

$("#runForm").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget, data = new FormData(form), launch = form.querySelector(".launch"), note=$("#formNote");
  const activeCount = state.runs.filter(item => ["queued","running"].includes(item.run.status)).length;
  if (activeCount && !confirm(`当前还有 ${activeCount} 轮正在运行或排队。继续会把新任务追加到队尾，是否继续？`)) return;
  launch.disabled = true; note.classList.remove("error"); note.textContent = "正在创建本地实验任务…";
  try {
    let extraBody;
    try { extraBody = JSON.parse(data.get("extra_body") || "{}"); } catch (_) { throw new Error("extra_body 不是有效 JSON"); }
    const concurrencyLevels = [...new Set(String(data.get("concurrency_levels")).split(/[\s,，/]+/).filter(Boolean).map(Number))];
    if (!concurrencyLevels.length || concurrencyLevels.some(value => !Number.isInteger(value) || value < 1 || value > 256)) {
      throw new Error("并发矩阵需为 1–256 的整数，例如：1, 2, 4, 8");
    }
    if (concurrencyLevels.length > 8) throw new Error("一次最多运行 8 个并发档位");
    const repetitions=Number(data.get("repetitions"));
    if (!Number.isInteger(repetitions) || repetitions < 3 || repetitions > 20) throw new Error("每个并发档至少运行 3 轮，最多 20 轮");
    const suiteId=createSuiteId(), suiteName=String(data.get("name"));
    const basePayload = {
      name:data.get("name"), framework:data.get("framework"), endpoint:data.get("endpoint"), model:data.get("model"),
      api_key:data.get("api_key") || null, api_key_env:data.get("api_key_env") || null,
      requests:Number(data.get("requests")), max_tokens:Number(data.get("max_tokens")),
      warmup_requests:Number(data.get("warmup_requests")), timeout_s:Number(data.get("timeout_s")), prompts:String(data.get("prompts")).split("\n").map(x=>x.trim()).filter(Boolean), extra_body:extraBody,
      suite_id:suiteId, suite_name:suiteName, repetitions, suite_total_runs:concurrencyLevels.length*repetitions
    };
    note.textContent = `正在创建 ${concurrencyLevels.length} 档 × ${repetitions} 轮实验…`;
    const results=[], failures=[];
    for (const concurrency of concurrencyLevels) {
      for (let repetition=1; repetition<=repetitions; repetition++) {
        const payload={...basePayload, concurrency, repetition, name:`${suiteName} · C${concurrency} · R${repetition}`};
        try { results.push(await api("/api/runs", {method:"POST", body:JSON.stringify(payload)})); }
        catch (error) { failures.push(error); }
      }
    }
    if (!results.length) throw failures[0];
    form.elements.api_key.value = "";
    state.selectedId=results[0].run.id;
    state.compareIds=results.map(result=>result.run.id);
    $("#compareBtn").disabled=true;
    $("#compareBtn").textContent="正在同步实验状态…";
    note.textContent=`已排队 ${results.length} 个 run；各轮串行执行，避免相互污染${failures.length ? `；${failures.length} 个创建失败` : ""}。`;
    await loadRuns(true); toast(`矩阵已启动：${concurrencyLevels.join(" / ")} × ${repetitions} 轮`);
  } catch(error) { note.textContent=error.message; note.classList.add("error"); }
  finally { launch.disabled=false; }
});

const presetConfig = {
  mock:{framework:"vllm", endpoint:`${location.origin}/mock/v1/chat/completions`, model:"demo-model", note:"C1 / C2 / C4 / C8 每档串行跑 3 轮；Compare 展示均值与稳定性。"},
  vllm:{framework:"vllm", endpoint:"http://YOUR-VLLM-HOST:8000/v1/chat/completions", model:"YOUR-MODEL", note:"填写 vLLM 云端地址；确认并发与请求量不会产生意外费用。"},
  sglang:{framework:"sglang", endpoint:"http://YOUR-SGLANG-HOST:30000/v1/chat/completions", model:"YOUR-MODEL", note:"填写 SGLang 云端地址；服务需兼容 OpenAI streaming。"}
};
$$('[data-preset]').forEach(button=>button.addEventListener("click",()=>{
  $$('.preset').forEach(item=>item.classList.remove("active")); button.classList.add("active");
  const config=presetConfig[button.dataset.preset], form=$("#runForm");
  form.elements.framework.value=config.framework; form.elements.endpoint.value=config.endpoint; form.elements.model.value=config.model; $("#formNote").textContent=config.note;
}));

$("#discoverBtn").addEventListener("click",async()=>{
  const form=$("#runForm"), button=$("#discoverBtn");
  button.disabled=true; button.innerHTML="<strong>正在连接 Models API…</strong>";
  try {
    const result=await api("/api/discover",{method:"POST",body:JSON.stringify({
      endpoint:form.elements.endpoint.value,
      api_key:form.elements.api_key.value || null,
      api_key_env:form.elements.api_key_env.value || null
    })});
    form.elements.endpoint.value=result.chat_endpoint;
    form.elements.model.value=result.models[0].id;
    const model=result.models[0], length=model.max_model_len ? ` · context ${Number(model.max_model_len).toLocaleString()}` : "";
    form.elements.name.value=String(model.id).slice(0, form.elements.name.maxLength || 80);
    $("#formNote").classList.remove("error");
    $("#formNote").textContent=`已识别 ${result.models.length} 个模型；已填写模型与实验名称：${model.id}${length}。`;
    toast(`连接成功：${model.id}`);
  } catch(error) {
    $("#formNote").classList.add("error"); $("#formNote").textContent=error.message;
  } finally { button.disabled=false; button.innerHTML="<span>⌁</span><strong>检测服务并自动填写模型与实验名称</strong><small>支持直接粘贴 /v1/models</small>"; }
});

$$('.view-tab').forEach(tab=>tab.addEventListener("click",()=>setView(tab.dataset.view)));
$("#compareBtn").addEventListener("click",runCompare);
$("#refreshBtn").addEventListener("click",()=>loadRuns(true));
$("#bulkModeBtn").addEventListener("click",()=>{
  state.bulkMode = !state.bulkMode;
  state.deleteIds = [];
  renderHistory();
});
$("#bulkSelectAllBtn").addEventListener("click",()=>{
  const deletable = state.runs.filter(item => !["queued","running"].includes(item.run.status)).map(item => item.run.id);
  state.deleteIds = deletable.length && deletable.every(id => state.deleteIds.includes(id)) ? [] : deletable;
  renderHistory();
});
$("#bulkDeleteBtn").addEventListener("click",async()=>{
  const ids = [...state.deleteIds];
  if (!ids.length || !confirm(`确定删除选中的 ${ids.length} 个实验及其全部本地样本？此操作不可撤销。`)) return;
  const button = $("#bulkDeleteBtn");
  button.disabled = true;
  button.textContent = "删除中…";
  let deleted = 0;
  const failures = [];
  for (const id of ids) {
    try { await api(`/api/runs/${encodeURIComponent(id)}`, {method:"DELETE"}); deleted += 1; }
    catch (error) { failures.push(error.message); }
  }
  state.compareIds = state.compareIds.filter(id => !ids.includes(id));
  const keepSelection = !ids.includes(state.selectedId);
  if (!keepSelection) state.selectedId = null;
  state.bulkMode = false;
  state.deleteIds = [];
  button.textContent = "删除";
  await loadRuns(keepSelection);
  toast(failures.length ? `已删除 ${deleted} 个，${failures.length} 个失败` : `已删除 ${deleted} 个实验`);
});
$("#cancelBtn").addEventListener("click",async()=>{ if(!state.selectedId)return; try{await api(`/api/runs/${state.selectedId}/cancel`,{method:"POST"});await loadRuns(true);toast("本轮已停止，连接已中断");}catch(error){toast(error.message);} });
$("#cancelSuiteBtn").addEventListener("click",async()=>{
  const suiteId=state.selected?.run.config.suite_id;
  if(!suiteId || !confirm("立即停止这一组中所有正在运行和排队的轮次？已完成的数据会保留。"))return;
  try {
    const result=await api(`/api/suites/${encodeURIComponent(suiteId)}/cancel`,{method:"POST"});
    await loadRuns(true);
    toast(`已停止整组：${result.cancelled} 轮`);
  } catch(error) { toast(error.message); }
});
$("#deleteBtn").addEventListener("click",async()=>{ if(!state.selectedId||!confirm("删除此实验及全部本地样本？"))return; try{await api(`/api/runs/${state.selectedId}`,{method:"DELETE"});state.compareIds=state.compareIds.filter(id=>id!==state.selectedId);state.selectedId=null;await loadRuns(false);toast("本地实验已删除");}catch(error){toast(error.message);} });

async function downloadRun(format) {
  if (!state.selectedId) return;
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(state.selectedId)}/export?format=${format}`);
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `inferbench-${state.selectedId}.${format}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { toast(`导出失败：${error.message}`); }
}

function inlineSnapshotStyles(source, clone) {
  const sourceNodes = [source, ...source.querySelectorAll("*")];
  const cloneNodes = [clone, ...clone.querySelectorAll("*")];
  sourceNodes.forEach((node, index) => {
    const target = cloneNodes[index];
    if (!target || !(node instanceof Element)) return;
    const computed = getComputedStyle(node);
    for (const property of computed) target.style.setProperty(property, computed.getPropertyValue(property), computed.getPropertyPriority(property));
  });
}

async function createElementSnapshot(source, footerText) {
  if (!source) throw new Error("没有可截图的内容");
  if (document.fonts?.ready) await document.fonts.ready;

  const bounds = source.getBoundingClientRect();
  const width = Math.max(640, Math.ceil(bounds.width));
  const height = Math.ceil(source.scrollHeight + 96);
  const clone = source.cloneNode(true);
  inlineSnapshotStyles(source, clone);
  clone.querySelectorAll("[data-capture-hide], .token-speed-tooltip").forEach(node => node.remove());
  clone.style.width = `${width}px`;
  clone.style.height = "auto";
  clone.style.padding = "24px";
  clone.style.margin = "0";
  clone.style.background = "#f8f9fc";
  clone.style.boxSizing = "border-box";
  clone.style.overflow = "hidden";
  clone.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");

  const footer = document.createElement("div");
  footer.textContent = footerText;
  footer.style.cssText = "display:flex;align-items:center;justify-content:flex-end;height:32px;margin-top:10px;color:#9da5b4;font:700 8px SFMono-Regular,Menlo,monospace;letter-spacing:.08em;border-top:1px solid #e3e7ef";
  clone.appendChild(footer);

  const serialized = new XMLSerializer().serializeToString(clone);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><foreignObject width="100%" height="100%">${serialized}</foreignObject></svg>`;
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  const image = new Image();
  await new Promise((resolve, reject) => {
    image.onload = resolve;
    image.onerror = () => reject(new Error("测试图渲染失败"));
    image.src = url;
  });
  const scale = Math.min(2, 4096 / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const context = canvas.getContext("2d");
  context.scale(scale, scale);
  context.fillStyle = "#f8f9fc";
  context.fillRect(0, 0, width, height);
  context.drawImage(image, 0, 0, width, height);
  return await new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error("PNG 生成失败")), "image/png"));
}

async function createTestSnapshot() {
  if (!state.selected) throw new Error("请先选择一个实验");
  return createElementSnapshot($("#detailCapture"), `INFERBENCH · ${state.selected.run.model} · ${new Date().toLocaleString("zh-CN", { hour12: false })}`);
}

function downloadSnapshot(blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `inferbench-${state.selectedId}-charts.png`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function copyTestSnapshot() {
  const button = $("#copyScreenshotBtn");
  const label = button.querySelector("span");
  button.disabled = true;
  label.textContent = "正在生成…";
  try {
    const blob = await createTestSnapshot();
    if (window.isSecureContext && navigator.clipboard?.write && window.ClipboardItem) {
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      button.classList.add("copied");
      label.textContent = "已复制";
      toast("测试图已复制到剪贴板，可直接粘贴");
      setTimeout(() => button.classList.remove("copied"), 1800);
    } else {
      downloadSnapshot(blob);
      label.textContent = "已下载";
      toast("当前页面不是安全连接，已下载 PNG 截图");
    }
  } catch (error) {
    label.textContent = "复制测试图";
    toast(`截图失败：${error.message}`);
  } finally {
    button.disabled = false;
    setTimeout(() => { label.textContent = "复制测试图"; }, 1800);
  }
}

function selectedReport() { return state.reports.find(report=>report.id===state.selectedReportId); }

async function generateSelectedSuiteReport() {
  const suiteId=state.selected?.run.config.suite_id;
  if(!suiteId) return;
  try {
    const report=await api("/api/reports",{method:"POST",body:JSON.stringify({suite_id:suiteId})});
    await loadReports(false);
    state.selectedReportId=report.id;
    renderReportPicker(); renderReport(); setView("report");
    toast("性能报告已生成");
  } catch(error) { toast(`报告生成失败：${error.message}`); }
}

function openReportSettings() {
  const report=selectedReport(); if(!report)return;
  const form=$("#reportSettingsForm"), criteria=report.criteria||{}, environment=report.environment||{};
  Object.entries(criteria).forEach(([key,value])=>{if(form.elements[key])form.elements[key].value=value??"";});
  ["hardware","framework_version","notes"].forEach(key=>{form.elements[key].value=environment[key]||"";});
  $("#reportSettingsDialog").showModal();
}

async function saveReportSettings() {
  const report=selectedReport(); if(!report)return;
  const form=$("#reportSettingsForm"), number=name=>form.elements[name].value===""?null:Number(form.elements[name].value);
  const payload={criteria:{min_success_rate:number("min_success_rate"),min_output_throughput_tps:number("min_output_throughput_tps"),max_ttft_p95_ms:number("max_ttft_p95_ms"),max_latency_p95_ms:number("max_latency_p95_ms")},environment:{hardware:form.elements.hardware.value.trim(),framework_version:form.elements.framework_version.value.trim(),notes:form.elements.notes.value.trim()}};
  const button=$("#saveReportSettingsBtn"); button.disabled=true;
  try { await api(`/api/reports/${encodeURIComponent(report.id)}`,{method:"PUT",body:JSON.stringify(payload)}); $("#reportSettingsDialog").close(); await loadReports(true); toast("评估标准已保存，报告已重新分析"); }
  catch(error){toast(`保存失败：${error.message}`);} finally{button.disabled=false;}
}

async function regenerateReport() {
  const report=selectedReport(); if(!report)return;
  try { await api(`/api/reports/${encodeURIComponent(report.id)}`,{method:"PUT",body:JSON.stringify({})}); await loadReports(true); toast("已基于当前原始数据重新生成快照"); }
  catch(error){toast(`重新分析失败：${error.message}`);}
}

async function downloadReportJson() {
  const report=selectedReport(); if(!report)return;
  const response=await fetch(`/api/reports/${encodeURIComponent(report.id)}/export`);
  if(!response.ok)return toast("报告 JSON 导出失败");
  downloadBlob(await response.blob(),`inferbench-${report.id}.json`);
}

function downloadBlob(blob, filename) {
  const url=URL.createObjectURL(blob), link=document.createElement("a"); link.href=url; link.download=filename; document.body.appendChild(link); link.click(); link.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000);
}

async function exportReportHtml() {
  const report=selectedReport(); if(!report)return;
  try {
    const css=await fetch("/static/styles.css").then(response=>response.text());
    const html=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>${esc(report.title)}</title><style>${css}\nbody{overflow:auto}.report-paper{display:block!important;max-width:1440px;margin:24px auto}.report-paper.hidden{display:block!important}</style></head><body><article class="report-paper">${$("#reportCapture").innerHTML}</article></body></html>`;
    downloadBlob(new Blob([html],{type:"text/html;charset=utf-8"}),`inferbench-${report.id}.html`); toast("已导出独立 HTML 报告");
  } catch(error){toast(`HTML 导出失败：${error.message}`);}
}

async function copyReportSnapshot() {
  const report=selectedReport(), button=$("#copyReportBtn"); if(!report)return;
  button.disabled=true; button.querySelector("span").textContent="正在生成…";
  try {
    const blob=await createElementSnapshot($("#reportCapture"),`INFERBENCH REPORT · ${report.id} · ${new Date().toLocaleString("zh-CN",{hour12:false})}`);
    if(window.isSecureContext&&navigator.clipboard?.write&&window.ClipboardItem){await navigator.clipboard.write([new ClipboardItem({"image/png":blob})]);toast("报告长图已复制到剪贴板");}
    else{downloadBlob(blob,`inferbench-${report.id}.png`);toast("当前连接不支持剪贴板，已下载报告长图");}
  } catch(error){toast(`长图生成失败：${error.message}`);} finally{button.disabled=false;button.querySelector("span").textContent="复制长图";}
}

$("#exportCsvBtn").addEventListener("click", () => downloadRun("csv"));
$("#exportJsonBtn").addEventListener("click", () => downloadRun("json"));
$("#copyScreenshotBtn").addEventListener("click", copyTestSnapshot);
$("#viewReportBtn").addEventListener("click",async()=>{
  const report=state.reports.find(item=>item.suite_id===state.selected?.run.config.suite_id);
  if(report){state.selectedReportId=report.id;renderReportPicker();renderReport();setView("report");}
  else await generateSelectedSuiteReport();
});
$("#reportSelect").addEventListener("change",event=>{state.selectedReportId=event.target.value;renderReport();});
$("#reportSettingsBtn").addEventListener("click",openReportSettings);
$("#saveReportSettingsBtn").addEventListener("click",saveReportSettings);
$("#regenerateReportBtn").addEventListener("click",regenerateReport);
$("#exportReportJsonBtn").addEventListener("click",downloadReportJson);
$("#exportReportHtmlBtn").addEventListener("click",exportReportHtml);
$("#copyReportBtn").addEventListener("click",copyReportSnapshot);
$("#printReportBtn").addEventListener("click",()=>{document.body.classList.add("print-report");window.print();});
window.addEventListener("afterprint",()=>document.body.classList.remove("print-report"));

document.addEventListener("visibilitychange",()=>{
  if(document.visibilityState === "hidden" && state.poller) {
    clearTimeout(state.poller);
    state.poller=null;
  } else if(document.visibilityState === "visible") {
    loadRuns(true);
  }
});

updateClock(); setInterval(updateClock,1000); checkHealth(); loadRuns(false);
