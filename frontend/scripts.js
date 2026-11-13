// frontend/scripts.js
const API_BASE = "https://modern-data-dashboard.onrender.com";
const STATS_URL = API_BASE + "/api/stats";
const DATA_URL = API_BASE + "/api/data";
const EXPORT_CSV = API_BASE + "/api/export/csv";
const EXPORT_EXCEL = API_BASE + "/api/export/excel";
const EXPORT_PDF = API_BASE + "/api/export/pdf";
const SCHEDULE_URL = API_BASE + "/api/schedule-email";
const SCHEDULES_URL = API_BASE + "/api/schedules";
const LOGIN_URL = API_BASE + "/api/login";
const REGISTER_URL = API_BASE + "/api/register";
const ME_URL = API_BASE + "/api/me";

// The backend runs on Render's free plan, which puts it to sleep when nobody has used it
// for a while. Waking it up takes up to a minute and requests can fail while it starts,
// so loading the data keeps retrying for this long before showing an error.
const WAKE_UP_WINDOW_MS = 100000;
const AUTH_RETRY_WINDOW_MS = 45000;
const REQUEST_TIMEOUT_MS = 70000;
const MIN_ATTEMPT_MS = 15000;
const WAKING_MESSAGE = "Loading the data. The server sleeps when nobody has used it for a while, so the first visit can take up to a minute.";

let dailySalesChart, productChart, regionChart;
let currentData = null;
let fullTableData = [];
let allDates = [];
let sortDirection = {};
let sortKey = null;
let latestStatsRequest = 0;
let latestLoad = 0;
let latestDateChange = 0;
let modalOpener = null;
let token = readStorage("dashboard_token");
let userEmail = readStorage("dashboard_email");

const el = (id) => document.getElementById(id);

// --- INIT ---
document.addEventListener("DOMContentLoaded", () => {
  el("footerYear").textContent = new Date().getFullYear();
  bindUI();
  initTableSorting();
  initSearch();
  initExportButtons();
  initPDFExport();
  initThemeToggle();
  updateAuthUI();
  loadDashboard();
});

// --- UI binding ---
function bindUI() {
  el("timeFilter").addEventListener("change", applyFiltersAndRender);
  el("regionFilter").addEventListener("change", refresh);
  el("productFilter").addEventListener("change", refresh);
  el("startDate").addEventListener("change", onDateChange);
  el("endDate").addEventListener("change", onDateChange);
  el("retryLoad").addEventListener("click", () => {
    showStatus("Trying again...");
    loadDashboard();
  });

  el("showAuth").addEventListener("click", () => (token ? logout() : openModal()));
  el("scheduleBtn").addEventListener("click", openModal);
  el("closeModal").addEventListener("click", closeModal);
  el("modal").addEventListener("click", (e) => { if (e.target === el("modal")) closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
  document.addEventListener("keydown", trapFocus);

  el("registerBtn").addEventListener("click", registerUser);
  el("loginBtn").addEventListener("click", loginUser);
  el("authPassword").addEventListener("keydown", (e) => { if (e.key === "Enter") loginUser(); });
  el("logoutBtn").addEventListener("click", logout);
  el("confirmSchedule").addEventListener("click", scheduleEmail);
  el("cancelSchedules").addEventListener("click", cancelSchedules);
}

// --- Talking to the API ---
class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.status = status;
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function fetchWithTimeout(url, options = {}, ms = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

// Returns the parsed JSON, or throws an ApiError with a message that can be shown as is.
// Failures that happen while Render is starting the server are retried for retryFor ms.
async function apiFetch(url, options = {}, { retryFor = 0 } = {}) {
  const giveUpAt = Date.now() + retryFor;
  for (let attempt = 1; ; attempt++) {
    let res;
    try {
      // Keep the whole thing close to the retry window instead of starting a long attempt at the end
      const timeLeft = giveUpAt - Date.now();
      res = await fetchWithTimeout(url, options, retryFor ? Math.min(REQUEST_TIMEOUT_MS, Math.max(timeLeft, MIN_ATTEMPT_MS)) : REQUEST_TIMEOUT_MS);
    } catch (err) {
      if (Date.now() < giveUpAt) {
        await sleep(Math.min(2000 * attempt, 8000));
        continue;
      }
      throw new ApiError("Can't reach the server right now. It may still be starting up.", 0);
    }
    const data = await res.json().catch(() => null);
    if (res.ok) return data || {};
    // While Render wakes the server it can answer with its own error page instead of
    // the app's JSON, so those answers are retried. Errors from the app itself are final.
    const fromApp = Boolean(data && typeof data.error === "string");
    if (!fromApp && [502, 503, 504].includes(res.status) && Date.now() < giveUpAt) {
      await sleep(Math.min(2000 * attempt, 8000));
      continue;
    }
    throw new ApiError(fromApp ? data.error : `The server answered with an error (${res.status}).`, res.status);
  }
}

function authHeaders() {
  return token ? { Authorization: "Bearer " + token } : {};
}

// --- Loading state ---
function showStatus(message, { error = false, retry = false } = {}) {
  el("serverStatusText").textContent = message;
  el("serverStatus").classList.toggle("error", error);
  el("retryLoad").hidden = !retry;
  el("serverStatus").hidden = false;
}

function hideStatus() {
  el("serverStatus").hidden = true;
}

function loadErrorMessage(err) {
  if (err.status === 0) {
    return "Couldn't load the data. The server may still be starting up, so give it a moment and try again.";
  }
  return "Couldn't load the data. " + err.message;
}

// Runs a load, shows the wake-up notice if it is slow and an error if it fails.
// Only the most recent load is allowed to change the notice.
async function runLoad(task) {
  const loadId = ++latestLoad;
  const isLatest = () => loadId === latestLoad;
  const slowNotice = setTimeout(() => { if (isLatest()) showStatus(WAKING_MESSAGE); }, 2500);
  try {
    await task();
    if (isLatest()) hideStatus();
  } catch (err) {
    if (isLatest()) showStatus(loadErrorMessage(err), { error: true, retry: true });
  } finally {
    clearTimeout(slowNotice);
  }
}

function loadDashboard() {
  return runLoad(async () => {
    // The filter options load alongside the data and are fetched once more if that fails
    initFilters().catch(() => setTimeout(() => initFilters().catch(() => {}), 5000));
    await fetchAndRender();
    verifySession();
  });
}

function refresh() {
  return runLoad(() => fetchAndRender());
}

// --- Fetch & Render ---
async function fetchAndRender() {
  const params = new URLSearchParams();
  const startDate = el("startDate").value;
  const endDate = el("endDate").value;
  if (startDate) params.append("start_date", startDate);
  if (endDate) params.append("end_date", endDate);

  const region = el("regionFilter").value;
  const product = el("productFilter").value;
  if (region) params.append("region", region);
  if (product) params.append("product", product);
  const url = STATS_URL + (params.toString() ? `?${params.toString()}` : "");

  const requestId = ++latestStatsRequest;
  const data = await apiFetch(url, {}, { retryFor: WAKE_UP_WINDOW_MS });
  if (requestId !== latestStatsRequest) return; // a newer filter change replaced this one
  currentData = data;
  updateSummaryCards(data);
  renderTable(data.table_data);
  renderCharts(data);
}

// --- updateSummaryCards ---
function updateSummaryCards(data) {
  el("total-sales").textContent = (data.total_sales || 0).toLocaleString();
  el("total-revenue").textContent = "$" + (data.total_revenue || 0).toLocaleString();
}

// --- Charts rendering ---
function renderCharts(data) {
  if (typeof Chart === "undefined") {
    showChartMessage("The charts couldn't load. Check your connection and refresh the page.");
    return;
  }
  showChartMessage("");

  const dailyLabels = (data.daily_sales || []).map(i => toISODate(i.date));
  const dailyValues = (data.daily_sales || []).map(i => i.sales);
  const productLabels = (data.sales_by_product || []).map(i => i.product);
  const productValues = (data.sales_by_product || []).map(i => i.sales);
  const regionLabels = (data.sales_by_region || []).map(i => i.region);
  const regionValues = (data.sales_by_region || []).map(i => i.sales);

  if (dailySalesChart) dailySalesChart.destroy();
  if (productChart) productChart.destroy();
  if (regionChart) regionChart.destroy();

  dailySalesChart = new Chart(el("dailySalesChart"), {
    type: "line",data: { labels: dailyLabels, datasets: [{ label: "Sales", data: dailyValues, borderColor: "#1a73e8", backgroundColor: "rgba(26,115,232,0.1)", tension:0.3, fill:true }]},
    options: { responsive:true, plugins:{legend:{display:false}}, scales:{ x:{ ticks:{ color:getTickColor() }}, y:{ ticks:{ color:getTickColor() }}}}
  });

  productChart = new Chart(el("productChart"), {
    type: "pie",
    data: { labels: productLabels, datasets: [{ data: productValues, backgroundColor:["#1a73e8","#34a853","#fbbc04","#ea4335","#9c27b0"] }]},
    options: { responsive:true, plugins:{legend:{position:"bottom"}}}
  });

  regionChart = new Chart(el("regionChart"), {
    type: "bar",
    data: { labels: regionLabels, datasets: [{ label:"Sales", data: regionValues, backgroundColor:"#34a853" }]},
    options: { responsive:true, plugins:{legend:{display:false}}, scales:{ x:{ ticks:{ color:getTickColor() }}, y:{ ticks:{ color:getTickColor() }}}}
  });
}

function showChartMessage(message) {
  document.querySelectorAll(".chart-box").forEach((box) => {
    let note = box.querySelector(".chart-message");
    if (!message) {
      if (note) note.remove();
      return;
    }
    if (!note) {
      note = document.createElement("p");
      note.className = "chart-message";
      box.appendChild(note);
    }
    note.textContent = message;
  });
}

// --- Filters population (region/product) ---
async function initFilters() {
  const rows = await apiFetch(DATA_URL, {}, { retryFor: WAKE_UP_WINDOW_MS });
  allDates = [...new Set(rows.map(r => toISODate(r.date)))].sort();
  fillSelect("regionFilter", [...new Set(rows.map(r => r.region))].filter(Boolean).sort(), "All Regions");
  fillSelect("productFilter", [...new Set(rows.map(r => r.product))].filter(Boolean).sort(), "All Products");
}

function fillSelect(id, values, allLabel) {
  const select = el(id);
  const current = select.value;
  select.innerHTML = "";
  select.appendChild(new Option(allLabel, ""));
  values.forEach(v => select.appendChild(new Option(v, v)));
  select.value = values.includes(current) ? current : "";
}

// --- applyFiltersAndRender from UI ---
function applyFiltersAndRender() {
  const preset = el("timeFilter").value;
  const dateChange = ++latestDateChange;
  return runLoad(async () => {
    // timeFilter preset (last 3/5) sets the start/end dates from the latest dates in the data
    if (preset === "last-3-days" || preset === "last-5-days") {
      if (!allDates.length) await initFilters();
      // Another date choice was made while the dates were loading, so that one wins
      if (dateChange !== latestDateChange) return;
      const count = preset === "last-3-days" ? 3 : 5;
      const lastDates = allDates.slice(-count);
      if (lastDates.length) {
        el("startDate").value = lastDates[0];
        el("endDate").value = lastDates[lastDates.length - 1];
      }
    } else if (preset === "all") {
      // if "all" selected, clear date inputs
      el("startDate").value = "";
      el("endDate").value = "";
    }
    // "custom" keeps whatever dates are already picked
    await fetchAndRender();
  });
}

// Picking a date by hand switches the preset to "Custom range" so it isn't overwritten
function onDateChange() {
  latestDateChange++;
  el("timeFilter").value = el("startDate").value || el("endDate").value ? "custom" : "all";
  refresh();
}

// --- Table rendering & sorting/search ---
function renderTable(data) {
  fullTableData = (data || []).map(row => ({ ...row, date: toISODate(row.date) }));
  updateTableView();
}

// Applies the search box and the chosen sort to the full table data, so clearing the
// search brings every row back
function updateTableView() {
  const term = el("searchInput").value.trim().toLowerCase();
  const rows = term
    ? fullTableData.filter(row => Object.values(row).some(v => String(v).toLowerCase().includes(term)))
    : [...fullTableData];
  if (sortKey) rows.sort(compareRows(sortKey, sortDirection[sortKey]));
  drawRows(rows);
}

function drawRows(rows) {
  const tbody = document.querySelector("#dataTable tbody");
  tbody.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "empty-row";
    td.textContent = fullTableData.length ? "No rows match your search." : "No sales match these filters.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  rows.forEach(row => {
    const tr = document.createElement("tr");
    [row.date, row.product, row.region, row.sales, "$" + row.revenue].forEach(value => {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function compareRows(key, ascending) {
  return (a, b) => {
    const result = key === "sales" || key === "revenue"
      ? Number(a[key]) - Number(b[key])
      : String(a[key]).localeCompare(String(b[key]));
    return ascending ? result : -result;
  };
}

function initTableSorting() {
  const headers = document.querySelectorAll("#dataTable th");
  headers.forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      sortDirection[key] = !sortDirection[key];
      sortKey = key;
      updateTableView();
    });
  });
}

function initSearch() {
  el("searchInput").addEventListener("input", updateTableView);
}

// --- Exports (CSV/Excel) ---
function initExportButtons() {
  el("exportCSV").addEventListener("click", () => exportData(EXPORT_CSV, "dashboard_data.csv", el("exportCSV")));
  el("exportExcel").addEventListener("click", () => exportData(EXPORT_EXCEL, "dashboard_data.xlsx", el("exportExcel")));
}

function exportData(baseUrl, filename, button){
  const params = new URLSearchParams();
  const region = el("regionFilter").value;
  const product = el("productFilter").value;
  const startDate = el("startDate").value;
  const endDate = el("endDate").value;
  if (region) params.append("region", region);
  if (product) params.append("product", product);
  if (startDate) params.append("start_date", startDate);
  if (endDate) params.append("end_date", endDate);
  return downloadFile(`${baseUrl}?${params.toString()}`, {}, filename, button);
}

// Downloads in the background, so a slow or failed export never takes the visitor
// away from the dashboard
async function downloadFile(url, options, filename, button) {
  button.disabled = true;
  try {
    const res = await fetchWithTimeout(url, options);
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      throw new ApiError(data && data.error ? data.error : `The export failed (${res.status}).`, res.status);
    }
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  } catch (err) {
    alert(err instanceof ApiError
      ? err.message
      : "Couldn't reach the server for the export. It may still be starting up, so try again in a minute.");
  } finally {
    button.disabled = false;
  }
}

// --- PDF export (sends chart images & summary to backend) ---
function initPDFExport() {
  el("exportPDF").addEventListener("click", exportPDF);
}

function exportPDF() {
  if (!dailySalesChart || !productChart || !regionChart) return alert("Charts not ready");
  const charts = {
    "Daily Sales Trend": dailySalesChart.toBase64Image(),
    "Sales by Product": productChart.toBase64Image(),
    "Sales by Region": regionChart.toBase64Image()
  };
  // Taken from the data rather than the cards, whose number format depends on the browser's language
  const summary = {
    total_sales: (currentData && currentData.total_sales) || 0,
    total_revenue: (currentData && currentData.total_revenue) || 0
  };
  return downloadFile(EXPORT_PDF, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({charts, summary})
  }, "dashboard_report.pdf", el("exportPDF"));
}

// --- Auth: Register & Login ---
function openModal() {
  setMessage("authMessage", "");
  setMessage("scheduleMessage", "");
  updateAuthUI();
  modalOpener = document.activeElement;
  el("modal").classList.remove("hidden");
  // Focus goes to the dialog itself rather than a field, so phones don't pop up the keyboard
  el("modalContent").focus();
}

function closeModal() {
  if (el("modal").classList.contains("hidden")) return;
  el("modal").classList.add("hidden");
  if (modalOpener && document.contains(modalOpener)) modalOpener.focus();
  modalOpener = null;
}

// Keeps keyboard focus inside the dialog while it is open
function trapFocus(e) {
  if (e.key !== "Tab" || el("modal").classList.contains("hidden")) return;
  const focusable = [...el("modalContent").querySelectorAll("button, input, select, textarea, a[href]")]
    .filter(node => !node.disabled && node.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = document.activeElement;
  if (!el("modalContent").contains(active)) {
    e.preventDefault();
    first.focus();
  } else if (e.shiftKey && (active === first || active === el("modalContent"))) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && active === last) {
    e.preventDefault();
    first.focus();
  }
}

function updateAuthUI() {
  const signedIn = Boolean(token);
  el("showAuth").textContent = signedIn ? "Log out" : "Login / Register";
  el("showAuth").title = signedIn && userEmail ? `Signed in as ${userEmail}` : "";
  el("authForms").hidden = signedIn;
  el("accountPanel").hidden = !signedIn;
  el("accountNote").textContent = userEmail ? `Signed in as ${userEmail}` : "You're signed in.";
  el("scheduleHint").hidden = signedIn;
  el("scheduleFields").hidden = !signedIn;
  if (signedIn && userEmail && !el("schedTargetEmail").value) el("schedTargetEmail").value = userEmail;
}

function setMessage(id, text, kind = "") {
  const node = el(id);
  node.textContent = text;
  node.className = "form-message" + (kind ? " " + kind : "");
}

function setBusy(ids, busy) {
  ids.forEach(id => { el(id).disabled = busy; });
}

function authErrorMessage(err) {
  if (err.status === 0) {
    return "Can't reach the server right now. It may still be starting up, so try again in a minute.";
  }
  return err.message;
}

function saveSession(newToken, email) {
  token = newToken;
  userEmail = email;
  writeStorage("dashboard_token", token);
  writeStorage("dashboard_email", email);
}

function clearSession() {
  token = null;
  userEmail = null;
  removeStorage("dashboard_token");
  removeStorage("dashboard_email");
  el("schedTargetEmail").value = "";
}

function logout() {
  clearSession();
  updateAuthUI();
  setMessage("scheduleMessage", "");
  setMessage("authMessage", "You're logged out.", "success");
  // The button that had focus is now hidden, so keep focus in the dialog if it's open
  if (!el("modal").classList.contains("hidden")) el("modalContent").focus();
}

async function submitAuth(url, pendingText) {
  const email = el("authEmail").value.trim();
  const password = el("authPassword").value;
  if (!email || !password) return setMessage("authMessage", "Enter your email and password.", "error");
  setBusy(["registerBtn", "loginBtn"], true);
  setMessage("authMessage", pendingText);
  try {
    const data = await apiFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    }, { retryFor: AUTH_RETRY_WINDOW_MS });
    if (!data.token) throw new ApiError("Something went wrong. Please try again.", 500);
    saveSession(data.token, data.email || email.toLowerCase());
    el("authPassword").value = "";
    setMessage("authMessage", "");
    setMessage("scheduleMessage", "");
    updateAuthUI();
    el("modalContent").focus();
  } catch (err) {
    setMessage("authMessage", authErrorMessage(err), "error");
  } finally {
    setBusy(["registerBtn", "loginBtn"], false);
  }
}

function registerUser() {
  return submitAuth(REGISTER_URL, "Creating your account...");
}

function loginUser() {
  return submitAuth(LOGIN_URL, "Logging in...");
}

// Checks that a saved login still works, since the server may have been reset
async function verifySession() {
  if (!token) return;
  const requestToken = token;
  try {
    const data = await apiFetch(ME_URL, { headers: authHeaders() });
    // Ignore the answer if the visitor logged out or in again while it was on its way
    if (data.email && token === requestToken) {
      userEmail = data.email;
      writeStorage("dashboard_email", userEmail);
      updateAuthUI();
    }
  } catch (err) {
    if (err.status === 401 && token === requestToken) {
      clearSession();
      updateAuthUI();
    }
  }
}

function sessionExpired(requestToken) {
  if (token !== requestToken) return;
  clearSession();
  updateAuthUI();
  setMessage("authMessage", "Your login has expired. Please log in again.", "error");
}

// --- Schedule email endpoint (calls backend to schedule job) ---
async function scheduleEmail() {
  if (!token) return setMessage("scheduleMessage", "Log in or register first.", "error");
  const target = el("schedTargetEmail").value.trim();
  if (!target) return setMessage("scheduleMessage", "Enter the email address the report should go to.", "error");
  const body = {
    target_email: target,
    region: el("regionFilter").value || null,
    product: el("productFilter").value || null,
    start_date: el("startDate").value || null,
    end_date: el("endDate").value || null,
    freq: el("schedFreq").value || "weekly"
  };
  setBusy(["confirmSchedule"], true);
  setMessage("scheduleMessage", "Scheduling...");
  const requestToken = token;
  try {
    const data = await apiFetch(SCHEDULE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body)
    });
    setMessage(
      "scheduleMessage",
      data.email_enabled === false
        ? "Saved. Email sending isn't switched on for this demo server, so no report will actually go out."
        : `Scheduled. A report will go to ${target} every week.`,
      "success"
    );
  } catch (err) {
    if (err.status === 401) {
      sessionExpired(requestToken);
      return;
    }
    setMessage("scheduleMessage", authErrorMessage(err), "error");
  } finally {
    setBusy(["confirmSchedule"], false);
  }
}

async function cancelSchedules() {
  if (!token) return setMessage("scheduleMessage", "Log in or register first.", "error");
  setBusy(["confirmSchedule", "cancelSchedules"], true);
  setMessage("scheduleMessage", "Cancelling...");
  const requestToken = token;
  try {
    const data = await apiFetch(SCHEDULES_URL, { method: "DELETE", headers: authHeaders() });
    const count = data.count || 0;
    setMessage(
      "scheduleMessage",
      count ? `Cancelled ${count} scheduled report${count === 1 ? "" : "s"}.` : "You don't have any scheduled reports.",
      "success"
    );
  } catch (err) {
    if (err.status === 401) {
      sessionExpired(requestToken);
      return;
    }
    setMessage("scheduleMessage", authErrorMessage(err), "error");
  } finally {
    setBusy(["confirmSchedule", "cancelSchedules"], false);
  }
}

// --- Theme toggle ---
function initThemeToggle(){
  const t = el("themeToggle");
  t.addEventListener("click", () => {
    document.body.classList.toggle("dark");
    t.textContent = document.body.classList.contains("dark") ? "☀️" : "🌙";
    if (currentData) renderCharts(currentData);
  });
}

function getTickColor(){
  return document.body.classList.contains("dark") ? "#f3f4f6" : "#666";
}

// --- Helpers ---
// Dates come back as YYYY-MM-DD. An older backend sent "Wed, 01 Jan 2025 00:00:00 GMT",
// which is converted so sorting and the date filters still work.
function toISODate(value) {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(0, 10);
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toISOString().slice(0, 10);
}

// Storage can be blocked (some private browsing modes), so it never breaks the page
function readStorage(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function writeStorage(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable */ }
}

function removeStorage(key) {
  try { localStorage.removeItem(key); } catch { /* storage unavailable */ }
}
