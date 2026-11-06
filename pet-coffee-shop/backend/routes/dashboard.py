# Brewskers dashboard route
# Daily sales, appointments and recent orders overview

import datetime

from flask import render_template

from backend.auth import app
from backend.config import LOW_STOCK_LIMIT
from backend.helpers import query
from backend.permissions import require


@app.get("/dashboard")
@require("dashboard.read")
def dashboard(user):
    today = datetime.date.today()

    todays_appointments = query(
        """SELECT a.*, s.name AS service_name
             FROM appointments a
             JOIN services s ON s.service_id = a.service_id
            WHERE a.appt_date = ?
              AND a.status != 'cancelled'
            ORDER BY a.appt_time""",
        (today,),
    )

    sales = query(
        """SELECT COUNT(*) AS order_count,
                  COALESCE(SUM(total_amount), 0) AS total_sales
             FROM orders
            WHERE DATE(order_date) = ?
              AND COALESCE(status, 'completed') != 'cancelled'""",
        (today,),
        one=True,
        default={"order_count": 0, "total_sales": 0},
    )

    low_stock_count = query(
        "SELECT COUNT(*) AS n FROM products WHERE stock <= ? AND status != 'hidden'",
        (LOW_STOCK_LIMIT,),
        one=True,
        default={"n": 0},
    )["n"]

    top_seller = query(
        """SELECT p.name
             FROM order_items i
             JOIN orders o ON o.order_id = i.order_id
             JOIN products p ON p.product_id = i.product_id
            WHERE DATE(o.order_date) = ?
            GROUP BY p.product_id, p.name
            ORDER BY SUM(i.quantity) DESC
            LIMIT 1""",
        (today,),
        one=True,
    )

    recent_orders = query(
        """SELECT o.order_id, o.order_no, o.customer_name, o.total_amount,
                  o.payment_method, o.order_date,
                  COALESCE(o.status, 'completed') AS status
             FROM orders o
            ORDER BY
              CASE WHEN COALESCE(o.status, 'completed') = 'queued' THEN 0 ELSE 1 END,
              o.order_date DESC, o.order_id DESC
            LIMIT 5"""
    )

    queued_count = query(
        "SELECT COUNT(*) AS n FROM orders WHERE COALESCE(status, 'completed') = 'queued'",
        one=True,
        default={"n": 0},
    )["n"]

    cancelled_count = query(
        "SELECT COUNT(*) AS n FROM orders WHERE COALESCE(status, 'completed') = 'cancelled'",
        one=True,
        default={"n": 0},
    )["n"]

    average_ticket = sales["total_sales"] / sales["order_count"] if sales["order_count"] else 0

    return render_template(
        "dashboard.html",
        user=user,
        active="dashboard",
        title="Dashboard",
        today=today,
        appointments=todays_appointments,
        sales=sales,
        low_stock_count=low_stock_count,
        top_seller=top_seller["name"] if top_seller else "-",
        average_ticket=average_ticket,
        recent_orders=recent_orders,
        queued_count=queued_count,
        cancelled_count=cancelled_count,
    )
