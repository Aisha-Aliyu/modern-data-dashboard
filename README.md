# Modern Data Dashboard 📊

A modern, interactive data dashboard built with HTML, CSS, JavaScript (Chart.js) on the frontend and Flask on the backend.  
It allows users to visualize, filter, search, export data, and schedule email reports — all from a clean, responsive interface.

---

## 🔗 Live Demo
Check out the live app here: [Modern Data Dashboard](https://cool-blancmange-531a43.netlify.app/)

---

## 📂 Features

### Dashboard
- Summary cards for total sales and total revenue
- Charts:
  - Daily Sales Trend (line chart)
  - Sales by Product (pie chart)
  - Sales by Region (bar chart)
- Interactive filtering:
  - By date range, product, region, or preset timeframes (last 3/5 days)
- Dark mode toggle 🌙

### Table
- Sortable and searchable data table
- Export options:
  - CSV
  - Excel
  - PDF (includes charts and summary)

### Authentication
- User registration and login
- Protected routes for scheduling reports

### Email Scheduling
- Schedule weekly email reports with filtered dashboard data
- Backend handles scheduling using APScheduler

---

## ⚙️ Tech Stack

Frontend:
- HTML5, CSS3
- JavaScript (ES6+)
- Chart.js
- Responsive design (mobile-friendly)

Backend:
- Python 3
- Flask
- Flask SQLAlchemy
- Flask-CORS
- JWT for authentication
- APScheduler for email scheduling
- Pandas, XlsxWriter, ReportLab for data export

---

## 💻 Installation (Local Development)

1. Clone the repo:
   ```bash
git clone https://github.com/Aisha-Aliyu/modern-data-dashboard.git
cd modern-data-dashboard

2. Setup Python backend:
   cd backend
python -m venv venv
source venv/bin/activate       # Linux/macOS
venv\Scripts\activate          # Windows
pip install -r requirements.txt

3. Run the Flask backend:
   export FLASK_APP=app.py
export FLASK_ENV=development   # Optional for dev
flask run

4. Frontend:

 • Open frontend/index.html in your browser or deploy on Netlify.

Make sure to update API_BASE in frontend/scripts.js with your backend URL.

⸻

🛠 Usage
 1. Register or login to access full features.
 2. Use filters to narrow down data by date, region, or product.
 3. Click table headers to sort data.
 4. Use export buttons to download CSV, Excel, or PDF reports.
 5. Schedule weekly email reports with your filtered dashboard.



```bash
git clone https://github.com/Aisha-Aliyu/modern-data-dashboard.git
cd modern-data-dashboard
