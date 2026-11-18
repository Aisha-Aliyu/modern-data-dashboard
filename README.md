# Modern Data Dashboard

A sales analytics dashboard with a Python and Flask backend and a plain JavaScript frontend. It shows sales as charts and a table, lets you filter and export the data, and can email you a report every week.

Live demo: https://cool-blancmange-531a43.netlify.app

## Features

### Dashboard

- Summary cards for total sales and total revenue.
- A line chart of daily sales, a pie chart of sales by product and a bar chart of sales by region, drawn with Chart.js.
- Filters for date range, product and region, plus quick presets for the last 3, 5 or 7 days.
- Light and dark mode.

### Data table

- Click a column header to sort by it.
- Search across every field as you type.
- Export to CSV, to Excel (formatted with XlsxWriter) or to PDF (with the charts, summary cards and table, built with ReportLab).

### Accounts and reports

- Register and log in. Sessions use JWTs, and you need to be logged in to export or schedule reports.
- Schedule a weekly email report with your filtered data and charts. The jobs run on APScheduler.

## Stack

- Frontend: HTML, CSS, JavaScript and Chart.js, hosted on Netlify.
- Backend: Python 3 and Flask, with SQLAlchemy (SQLite or PostgreSQL), Pandas for the data work, XlsxWriter and ReportLab for exports, and APScheduler for the weekly emails.

## Run it locally

You'll need Python 3.9 or newer. Node.js is only needed if you want to serve the frontend with `npx`.

```bash
git clone https://github.com/Aisha-Aliyu/modern-data-dashboard.git
cd modern-data-dashboard/backend
python -m venv venv
source venv/bin/activate      # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

You can add a `.env` file in `backend`. Everything in it is optional when you run locally. Without `DASH_DB_URI` the app uses a SQLite file, and without the SMTP settings scheduled reports are saved but not emailed.

```env
# Postgres connection string; leave it out to use SQLite
DASH_DB_URI=postgresql://user:password@host:5432/dbname
# Long random string used to sign logins
DASH_JWT_SECRET=your_long_random_secret
DASH_SMTP_HOST=smtp.gmail.com
DASH_SMTP_PORT=587
DASH_SMTP_USER=your_email@gmail.com
DASH_SMTP_PASS=your_app_password
```

Start the backend. It runs at http://localhost:5000.

```bash
export FLASK_APP=app.py
flask run
```

Then open `frontend/index.html` in your browser, or serve it with `npx http-server frontend -p 3000` from the project root. Set `API_BASE` in `frontend/scripts.js` to your backend URL.

## Deployment

The frontend is on Netlify. The backend can run on Render, Railway or any host that runs Python, with the environment variables set in the host's dashboard.

On a free host whose disk resets on restart (Render, for example), set `DASH_DB_URI` to a hosted Postgres database so accounts are kept, and set `DASH_JWT_SECRET` so logins survive restarts. Run a single gunicorn worker (the default), because the weekly reports are scheduled inside the web process.

## What I'd add next

Live updates over WebSockets, admin and viewer roles, a custom date range picker, shareable dashboard links and team workspaces.

## Contact

Aisha Aliyu, full stack and frontend engineer

- Portfolio: https://humairah.netlify.app
- LinkedIn: https://www.linkedin.com/in/aisha-aliyu-dev
- GitHub: https://github.com/Aisha-Aliyu

License: MIT
