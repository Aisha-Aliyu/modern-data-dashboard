# 📊 Modern Data Dashboard

> A full-stack interactive analytics dashboard with real-time data visualisation, advanced filtering, multi-format exports, JWT authentication, and scheduled email reports.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Visit%20App-brightgreen?style=for-the-badge)](https://cool-blancmange-531a43.netlify.app/)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-Backend-000000?style=for-the-badge&logo=flask)](https://flask.palletsprojects.com/)
[![JavaScript](https://img.shields.io/badge/JavaScript-ES6+-F7DF1E?style=for-the-badge&logo=javascript)](https://developer.mozilla.org/en-US/docs/Web/JavaScript)
[![Chart.js](https://img.shields.io/badge/Chart.js-Visualisation-FF6384?style=for-the-badge&logo=chart.js)](https://www.chartjs.org/)
[![JWT](https://img.shields.io/badge/JWT-Authentication-000000?style=for-the-badge&logo=jsonwebtokens)](https://jwt.io/)

-----

## 🌐 Live Demo

👉 **[modern-data-dashboard.netlify.app](https://cool-blancmange-531a43.netlify.app/)**

-----

## 📖 About

A production-grade full-stack data dashboard that demonstrates end-to-end engineering skills — from a Python/Flask REST API with JWT authentication and database management, to a responsive JavaScript frontend with interactive Chart.js visualisations and multi-format data exports.

This project highlights the ability to build internal tooling and analytics platforms that real businesses use — not just CRUD apps.

-----

## ✨ Features

### 📈 Dashboard & Visualisation

- Summary KPI cards (total sales, total revenue)
- **Line chart** — Daily sales trend over time
- **Pie chart** — Sales breakdown by product
- **Bar chart** — Sales performance by region
- Interactive filters: date range, product, region, preset timeframes (last 3/5/7 days)
- Light / dark mode toggle 🌙

### 📋 Data Table

- Sortable columns (click header to sort ascending/descending)
- Live search filtering across all fields
- **Export to CSV** — raw data download
- **Export to Excel** — formatted spreadsheet via XlsxWriter
- **Export to PDF** — includes charts, summary cards, and table via ReportLab

### 🔐 Authentication

- User registration and login
- JWT-based session management
- Protected routes for scheduling and export features

### 📧 Scheduled Email Reports

- Schedule automated weekly email reports
- Reports include filtered dashboard data and charts
- Background job scheduling via **APScheduler**

-----

## 🛠️ Tech Stack

|Layer           |Technology                              |
|----------------|----------------------------------------|
|Frontend        |HTML5, CSS3, JavaScript (ES6+), Chart.js|
|Backend         |Python 3, Flask                         |
|Database        |SQLAlchemy (SQLite / PostgreSQL)        |
|Auth            |JWT (JSON Web Tokens)                   |
|Data Processing |Pandas                                  |
|Excel Export    |XlsxWriter                              |
|PDF Export      |ReportLab                               |
|Email Scheduling|APScheduler                             |
|Frontend Deploy |Netlify                                 |
|Backend Deploy  |(configurable: Railway, Render, Heroku) |

-----

## 📂 Project Structure

```
modern-data-dashboard/
├─ backend/
│  ├─ app.py              # Flask application & API routes
│  ├─ models.py           # SQLAlchemy database models
│  ├─ auth.py             # JWT authentication logic
│  ├─ scheduler.py        # APScheduler email jobs
│  ├─ exports.py          # CSV / Excel / PDF generation
│  └─ requirements.txt    # Python dependencies
├─ frontend/
│  ├─ index.html          # Main dashboard
│  ├─ login.html          # Auth pages
│  ├─ scripts.js          # Chart.js, filters, API calls
│  └─ styles.css          # Responsive UI styles
├─ requirements.txt       # Root dependencies
└─ README.md
```

-----

## ⚙️ Getting Started

### Prerequisites

- Python 3.8+
- Node.js (optional, for frontend tooling)

### 1. Clone the repo

```bash
git clone https://github.com/Aisha-Aliyu/modern-data-dashboard.git
cd modern-data-dashboard
```

### 2. Set up the Python backend

```bash
cd backend
python -m venv venv

# Activate virtual environment
source venv/bin/activate       # Linux/macOS
venv\Scripts\activate          # Windows

pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in `/backend`:

```env
SECRET_KEY=your_jwt_secret_key
DATABASE_URL=sqlite:///dashboard.db
MAIL_USERNAME=your_email@gmail.com
MAIL_PASSWORD=your_email_password
```

### 4. Run the Flask backend

```bash
export FLASK_APP=app.py
flask run
```

Backend runs at <http://localhost:5000>

### 5. Run the frontend

Open `frontend/index.html` directly in your browser, or serve it:

```bash
npx http-server frontend -p 3000
```

> Make sure to update `API_BASE` in `frontend/scripts.js` to point to your backend URL.

-----

## 🚀 Deployment

**Frontend** is deployed on **Netlify** — connect your GitHub repo for automatic deployments.

**Backend** can be deployed on [Railway](https://railway.app/), [Render](https://render.com/), or any Python-compatible host. Set your environment variables in the platform dashboard.

-----

## 🗺️ Roadmap

- [ ] Real-time data updates via WebSockets
- [ ] Role-based access control (Admin / Viewer)
- [ ] Custom date range picker
- [ ] Dashboard sharing via public links
- [ ] Multi-user support with team workspaces

-----

## 👩‍💻 Author

**Aisha Aliyu** — Full-Stack & Frontend Engineer

- 🌐 Portfolio: [humairah.netlify.app](https://humairah.netlify.app)
- 💼 LinkedIn: [linkedin.com/in/aisha-aliyu-628b41376](https://www.linkedin.com/in/aisha-aliyu-628b41376)
- 🐙 GitHub: [@Aisha-Aliyu](https://github.com/Aisha-Aliyu)

-----

## 📜 License

This project is open source and available under the [MIT License](./LICENSE).