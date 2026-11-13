import csv
import os
import re

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sales_data.csv")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def csv_rows():
    with open(CSV_PATH, newline="") as f:
        return list(csv.DictReader(f))


def register(client, email, password="correct horse"):
    return client.post("/api/register", json={"email": email, "password": password})


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_health_reports_database(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.get_json()
    assert body["database"] == "ok"
    assert body["database_engine"] == "sqlite"


def test_stats_match_the_csv_and_use_iso_dates(client):
    rows = csv_rows()
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_sales"] == sum(int(r["sales"]) for r in rows)
    assert data["total_revenue"] == sum(int(r["revenue"]) for r in rows)
    assert len(data["daily_sales"]) == len({r["date"] for r in rows})
    assert [r["date"] for r in data["table_data"]] == sorted(r["date"] for r in rows)
    assert all(ISO_DATE.match(r["date"]) for r in data["table_data"])


def test_stats_filters(client):
    rows = [r for r in csv_rows()
            if r["region"].lower() == "north" and "2025-01-01" <= r["date"] <= "2025-01-05"]
    res = client.get("/api/stats?region=NORTH&start_date=2025-01-01&end_date=2025-01-05")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_sales"] == sum(int(r["sales"]) for r in rows)
    assert len(data["table_data"]) == len(rows)


def test_bad_date_filter_is_a_400(client):
    res = client.get("/api/stats?start_date=not-a-date")
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_data_endpoint_uses_iso_dates(client):
    res = client.get("/api/data")
    assert res.status_code == 200
    rows = res.get_json()
    assert len(rows) == len(csv_rows())
    assert all(ISO_DATE.match(r["date"]) for r in rows)


def test_register_login_and_me(client):
    assert register(client, "recruiter@example.com", password="short").status_code == 400
    assert register(client, "not-an-email").status_code == 400

    res = register(client, "Recruiter@Example.com")
    assert res.status_code == 200
    body = res.get_json()
    assert body["token"]
    assert body["email"] == "recruiter@example.com"

    assert register(client, "recruiter@example.com").status_code == 409

    wrong = client.post("/api/login", json={"email": "recruiter@example.com", "password": "wrong password"})
    assert wrong.status_code == 401

    good = client.post("/api/login", json={"email": "RECRUITER@example.com", "password": "correct horse"})
    assert good.status_code == 200
    token = good.get_json()["token"]

    me = client.get("/api/me", headers=auth_header(token))
    assert me.status_code == 200
    assert me.get_json()["email"] == "recruiter@example.com"
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers=auth_header("not-a-token")).status_code == 401


def test_repeated_wrong_passwords_are_slowed_down(client):
    assert register(client, "target@example.com").status_code == 200
    for _ in range(8):
        res = client.post("/api/login", json={"email": "target@example.com", "password": "guess guess"})
        assert res.status_code == 401
    res = client.post("/api/login", json={"email": "target@example.com", "password": "correct horse"})
    assert res.status_code == 429


def test_someone_else_cannot_lock_you_out(client):
    assert register(client, "victim@example.com").status_code == 200
    attacker = {"CF-Connecting-IP": "203.0.113.5"}
    for _ in range(8):
        client.post("/api/login", json={"email": "victim@example.com", "password": "guess guess"}, headers=attacker)
    blocked = client.post("/api/login", json={"email": "victim@example.com", "password": "guess guess"}, headers=attacker)
    assert blocked.status_code == 429

    owner = {"CF-Connecting-IP": "198.51.100.7"}
    res = client.post("/api/login", json={"email": "victim@example.com", "password": "correct horse"}, headers=owner)
    assert res.status_code == 200


def test_faked_forwarded_for_does_not_dodge_the_limit(client):
    statuses = []
    for i in range(21):
        headers = {"X-Forwarded-For": f"10.0.0.{i}, 192.0.2.50"}
        res = client.post("/api/login", json={"email": f"nobody{i}@example.com", "password": "guess guess"}, headers=headers)
        statuses.append(res.status_code)
    assert statuses[:20] == [401] * 20
    assert statuses[20] == 429


def test_schedule_needs_login_and_has_limits(client, dashboard):
    token = register(client, "scheduler@example.com").get_json()["token"]
    payload = {"target_email": "boss@example.com", "region": "North", "start_date": "2025-01-01"}

    assert client.post("/api/schedule-email", json=payload).status_code == 401
    bad_target = client.post("/api/schedule-email", json={"target_email": "nope"}, headers=auth_header(token))
    assert bad_target.status_code == 400

    # Scheduling the same address again updates the schedule rather than adding one
    for region in ("North", "South"):
        res = client.post("/api/schedule-email", json={**payload, "region": region}, headers=auth_header(token))
        assert res.status_code == 200
        assert res.get_json()["email_enabled"] is False
    schedules = client.get("/api/schedules", headers=auth_header(token)).get_json()["schedules"]
    assert len(schedules) == 1
    assert schedules[0]["region"] == "South"

    for i in range(2, dashboard.MAX_SCHEDULES_PER_USER + 1):
        res = client.post("/api/schedule-email", json={"target_email": f"boss{i}@example.com"}, headers=auth_header(token))
        assert res.status_code == 200
    over = client.post("/api/schedule-email", json={"target_email": "one-more@example.com"}, headers=auth_header(token))
    assert over.status_code == 400

    # Cancelling frees the slots again
    cancelled = client.delete("/api/schedules", headers=auth_header(token))
    assert cancelled.status_code == 200
    assert cancelled.get_json()["count"] == dashboard.MAX_SCHEDULES_PER_USER
    assert client.get("/api/schedules", headers=auth_header(token)).get_json()["schedules"] == []
    assert client.delete("/api/schedules").status_code == 401


def test_one_inbox_cannot_be_flooded_from_many_accounts(client, dashboard):
    payload = {"target_email": "shared-inbox@example.com"}
    for i in range(dashboard.MAX_SCHEDULES_PER_TARGET):
        token = register(client, f"sender{i}@example.com").get_json()["token"]
        assert client.post("/api/schedule-email", json=payload, headers=auth_header(token)).status_code == 200
    token = register(client, "sender-extra@example.com").get_json()["token"]
    assert client.post("/api/schedule-email", json=payload, headers=auth_header(token)).status_code == 400


def test_exports(client):
    csv_res = client.get("/api/export/csv?region=North")
    assert csv_res.status_code == 200
    assert csv_res.mimetype == "text/csv"
    assert csv_res.data.decode().splitlines()[0] == "date,product,region,sales,revenue"

    xlsx = client.get("/api/export/excel")
    assert xlsx.status_code == 200
    assert xlsx.data[:2] == b"PK"

    pdf = client.post("/api/export/pdf", json={
        "charts": {
            "Daily Sales Trend": TINY_PNG,
            "<img src='/etc/hosts' width='10' height='10'/>": TINY_PNG,
            "Broken": "not base64 at all!",
        },
        "summary": {"total_sales": 940, "total_revenue": "oops"},
    })
    assert pdf.status_code == 200
    assert pdf.data[:4] == b"%PDF"
