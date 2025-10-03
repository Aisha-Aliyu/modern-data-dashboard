// frontend/scripts.js
const API_BASE = "http://127.0.0.1:5000";
const STATS_URL = API_BASE + "/api/stats";
const EXPORT_CSV = API_BASE + "/api/export/csv";
const EXPORT_EXCEL = API_BASE + "/api/export/excel";
const EXPORT_PDF = API_BASE + "/api/export/pdf";
const SCHEDULE_URL = API_BASE + "/api/schedule-email";
const LOGIN_URL = API_BASE + "/api/login";
const REGISTER_URL = API_BASE + "/api/register";

let dailySalesChart, productChart, regionChart;
let currentData = null;
let fullTableData = [];
let sortDirection = {};
let token = localStorage.getItem("dashboard_token") || null;

// --- INIT ---
document.addEventListener("DOMContentLoaded", () => {
  initFilters();            // populates region/product selects
  bindUI();
  fetchAndRender();
  initTableSorting();
  initSearch();
  initExportButtons();
  initPDFExport();
  initThemeToggle();
});

// --- UI binding ---
function bindUI() {
  document.getElementById("timeFilter").addEventListener("change", applyFiltersAndRender);
  document.getElementById("regionFilter").addEventListener("change", applyFiltersAndRender);
  document.getElementById("productFilter").addEventListener("change", applyFiltersAndRender);
  document.getElementById("startDate").addEventListener("change", applyFiltersAndRender);
  document.getElementById("endDate").addEventListener("change", applyFiltersAndRender);
  document.getElementById("showAuth").addEventListener("click", () => document.getElementById("modal").classList.remove("hidden"));
  document.getElementById("closeModal").addEventListener("click", () => document.getElementById("modal").classList.add("hidden"));
  document.getElementById("registerBtn").addEventListener("click", registerUser);
  document.getElementById("loginBtn").addEventListener("click", loginUser);
  document.getElementById("scheduleBtn").addEventListener("click", () => {
    // bring up scheduler fields in modal
    document.getElementById("modal").classList.remove("hidden");
  });
  document.getElementById("confirmSchedule").addEventListener("click", scheduleEmail);
}

// --- Fetch & Render ---
async function fetchAndRender(filters = {}) {
  const params = new URLSearchParams();
  const startDate = document.getElementById("startDate").value;
  const endDate = document.getElementById("endDate").value;
  if (startDate) params.append("start_date", startDate);
  if (endDate) params.append("end_date", endDate);

  const region = document.getElementById("regionFilter").value;
  const product = document.getElementById("productFilter").value;
  if (region) params.append("region", region);
  if (product) params.append("product", product);

  // if a specific filter param passed (explicit call), append them as well
  if (filters.region) params.set("region", filters.region);
  if (filters.product) params.set("product", filters.product);
  const url = STATS_URL + (params.toString() ? `?${params.toString()}` : "");
  const res = await fetch(url);
  const data = await res.json();
  currentData = data;
  updateSummaryCards(data);
  renderCharts(data);
  renderTable(data.table_data);
}

// --- updateSummaryCards ---
function updateSummaryCards(data) {
  document.getElementById("total-sales").textContent = (data.total_sales || 0).toLocaleString();
  document.getElementById("total-revenue").textContent = "$" + (data.total_revenue || 0).toLocaleString();
}

// --- Charts rendering ---
function renderCharts(data) {
  const dailyLabels = (data.daily_sales || []).map(i => i.date);
  const dailyValues = (data.daily_sales || []).map(i => i.sales);
  const productLabels = (data.sales_by_product || []).map(i => i.product);
  const productValues = (data.sales_by_product || []).map(i => i.sales);
  const regionLabels = (data.sales_by_region || []).map(i => i.region);
  const regionValues = (data.sales_by_region || []).map(i => i.sales);

  if (dailySalesChart) dailySalesChart.destroy();
  if (productChart) productChart.destroy();
  if (regionChart) regionChart.destroy();

  dailySalesChart = new Chart(document.getElementById("dailySalesChart"), {
    type: "line",data: { labels: dailyLabels, datasets: [{ label: "Sales", data: dailyValues, borderColor: "#1a73e8", backgroundColor: "rgba(26,115,232,0.1)", tension:0.3, fill:true }]},
    options: { responsive:true, plugins:{legend:{display:false}}, scales:{ x:{ ticks:{ color:getTickColor() }}, y:{ ticks:{ color:getTickColor() }}}}
  });

  productChart = new Chart(document.getElementById("productChart"), {
    type: "pie",
    data: { labels: productLabels, datasets: [{ data: productValues, backgroundColor:["#1a73e8","#34a853","#fbbc04","#ea4335","#9c27b0"] }]},
    options: { responsive:true, plugins:{legend:{position:"bottom"}}}
  });

  regionChart = new Chart(document.getElementById("regionChart"), {
    type: "bar",
    data: { labels: regionLabels, datasets: [{ label:"Sales", data: regionValues, backgroundColor:"#34a853" }]},
    options: { responsive:true, plugins:{legend:{display:false}}, scales:{ x:{ ticks:{ color:getTickColor() }}, y:{ ticks:{ color:getTickColor() }}}}
  });
}

// --- Filters population (region/product) ---
async function initFilters() {
  const res = await fetch(API_BASE + "/api/data");
  const rows = await res.json();
  const regions = [...new Set(rows.map(r => r.region))].filter(Boolean).sort();
  const products = [...new Set(rows.map(r => r.product))].filter(Boolean).sort();
  const regionSelect = document.getElementById("regionFilter");
  const productSelect = document.getElementById("productFilter");
  regions.forEach(r => { const opt = document.createElement("option"); opt.value = r; opt.textContent = r; regionSelect.appendChild(opt); });
  products.forEach(p => { const opt = document.createElement("option"); opt.value = p; opt.textContent = p; productSelect.appendChild(opt); });
}

// --- applyFiltersAndRender from UI ---
function applyFiltersAndRender() {
  // timeFilter preset (last 3/5) will override start/end dates
  const preset = document.getElementById("timeFilter").value;
  if (preset === "last-3-days" || preset === "last-5-days") {
    // calculate dates based on current data (if available)
    // use raw data endpoint for full dates
    fetch(API_BASE + "/api/data").then(r => r.json()).then(rows => {
      const sorted = rows.map(r => r.date).sort();
      if (!sorted.length) return;
      let count = preset === "last-3-days" ? 3 : 5;
      const lastDates = sorted.slice(-count);
      document.getElementById("startDate").value = lastDates[0];
      document.getElementById("endDate").value = lastDates[lastDates.length-1];
      fetchAndRender();
    });
    return;
  }

  // if "all" selected, clear date inputs
  if (preset === "all") {
    document.getElementById("startDate").value = "";
    document.getElementById("endDate").value = "";
  }
  fetchAndRender();
}

// --- Table rendering & sorting/search ---
function renderTable(data) {
  fullTableData = data || [];
  const tbody = document.querySelector("#dataTable tbody");
  tbody.innerHTML = "";
  (data || []).forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${row.date}</td><td>${row.product}</td><td>${row.region}</td><td>${row.sales}</td><td>$${row.revenue}</td>`;
    tbody.appendChild(tr);
  });
}

function initTableSorting() {
  const headers = document.querySelectorAll("#dataTable th");
  headers.forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      sortDirection[key] = !sortDirection[key];
      const sorted = [...fullTableData].sort((a,b) => {
        if (key === "sales" || key === "revenue") {
          return sortDirection[key] ? a[key] - b[key] : b[key] - a[key];
        } else {
          return sortDirection[key] ? a[key].localeCompare(b[key]) : b[key].localeCompare(a[key]);
        }
      });
      renderTable(sorted);
    });
  });
}

function initSearch() {
  const input = document.getElementById("searchInput");
  input.addEventListener("input", e => {
    const term = e.target.value.toLowerCase();
    const filtered = fullTableData.filter(row => Object.values(row).some(v => String(v).toLowerCase().includes(term)));renderTable(filtered);
  });
}

// --- Exports (CSV/Excel) ---
function initExportButtons() {
  document.getElementById("exportCSV").addEventListener("click", () => exportData("csv"));
  document.getElementById("exportExcel").addEventListener("click", () => exportData("excel"));
}

function exportData(format){
  const params = new URLSearchParams();
  const region = document.getElementById("regionFilter").value;
  const product = document.getElementById("productFilter").value;
  const startDate = document.getElementById("startDate").value;
  const endDate = document.getElementById("endDate").value;
  if (region) params.append("region", region);
  if (product) params.append("product", product);
  if (startDate) params.append("start_date", startDate);
  if (endDate) params.append("end_date", endDate);
  const url = `${API_BASE}/api/export/${format}?${params.toString()}`;
  window.location.href = url;
}

// --- PDF export (sends chart images & summary to backend) ---
function initPDFExport() {
  document.getElementById("exportPDF").addEventListener("click", exportPDF);
}

async function exportPDF() {
  if (!dailySalesChart || !productChart || !regionChart) return alert("Charts not ready");
  const charts = {
    "Daily Sales Trend": dailySalesChart.toBase64Image(),
    "Sales by Product": productChart.toBase64Image(),
    "Sales by Region": regionChart.toBase64Image()
  };
  const summary = {
    total_sales: parseInt(document.getElementById("total-sales").textContent.replace(/,/g,"")),
    total_revenue: parseFloat(document.getElementById("total-revenue").textContent.replace(/[$,]/g,""))
  };
  const res = await fetch(EXPORT_PDF, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({charts, summary})
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "dashboard_report.pdf"; document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

// --- Auth: Register & Login ---
async function registerUser() {
  const email = document.getElementById("authEmail").value;
  const password = document.getElementById("authPassword").value;
  if (!email || !password) return alert("Email & password required");
  const res = await fetch(REGISTER_URL, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email,password})});
  const data = await res.json();
  if (res.ok) {
    token = data.token;
    localStorage.setItem("dashboard_token", token);
    alert("Registered & logged in");
    document.getElementById("modal").classList.add("hidden");
  } else {
    alert(data.error || "Registration failed");
  }
}

async function loginUser() {
  const email = document.getElementById("authEmail").value;
  const password = document.getElementById("authPassword").value;
  if (!email || !password) return alert("Email & password required");
  const res = await fetch(LOGIN_URL, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email,password})});
  const data = await res.json();
  if (res.ok) {
    token = data.token;
    localStorage.setItem("dashboard_token", token);
    alert("Logged in");
    document.getElementById("modal").classList.add("hidden");
  } else {
    alert(data.error || "Login failed");
  }
}

// --- Schedule email endpoint (calls backend to schedule job) ---
async function scheduleEmail() {
  if (!token) return alert("Please login/register first.");
  const target = document.getElementById("schedTargetEmail").value || prompt("Send report to email:");
  if (!target) return alert("Target email required.");
  const region = document.getElementById("regionFilter").value || null;
  const product = document.getElementById("productFilter").value || null;
  const start_date = document.getElementById("startDate").value || null;
  const end_date = document.getElementById("endDate").value || null;

  const body = { target_email: target, region, product, start_date, end_date, freq: "weekly" };const res = await fetch(SCHEDULE_URL, {method:"POST", headers:{"Content-Type":"application/json","Authorization": "Bearer " + token}, body: JSON.stringify(body)});
  const data = await res.json();
  if (res.ok) {
    alert("Scheduled! You will receive reports weekly.");
    document.getElementById("modal").classList.add("hidden");
  } else {
    alert(data.error || "Failed to schedule");
  }
}

// --- Theme toggle ---
function initThemeToggle(){
  const t = document.getElementById("themeToggle");
  t.addEventListener("click", () => {
    document.body.classList.toggle("dark");
    t.textContent = document.body.classList.contains("dark") ? "☀️" : "🌙";
    if (currentData) renderCharts(currentData);
  });
}

function getTickColor(){
  return document.body.classList.contains("dark") ? "#f3f4f6" : "#666";
}