# Brewskers reports route
# Sales summary, top sellers, daily trend, low stock and upcoming appointments

import datetime

from flask import render_template

from backend.auth import app
from backend.helpers import query
from backend.permissions import admin_required
from backend.settings import get_store_settings


@app.get("/reports")
@admin_required
def reports_page(user):
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=6)

    today_sales = query(
        """SELECT COUNT(*) AS order_count,
                  COALESCE(SUM(total_amount), 0) AS total_sales
             FROM orders
            WHERE DATE(order_date) = ?""",
        (today,),
        one=True,
        default={"order_count": 0, "total_sales": 0},
    )

    week_sales = query(
        """SELECT COUNT(*) AS order_count,
                  COALESCE(SUM(total_amount), 0) AS total_sales
             FROM orders
            WHERE DATE(order_date) >= ?""",
        (week_ago,),
        one=True,
        default={"order_count": 0, "total_sales": 0},
    )

    top_sellers = query(
        """SELECT p.name,
                  SUM(i.quantity) AS qty,
                  SUM(i.quantity * i.price) AS revenue
             FROM order_items i
             JOIN orders o ON o.order_id = i.order_id
             JOIN products p ON p.product_id = i.product_id
            WHERE DATE(o.order_date) >= ?
            GROUP BY p.product_id, p.name
            ORDER BY qty DESC
            LIMIT 5""",
        (week_ago,),
    )

    daily = query(
        """SELECT DATE(order_date) AS day,
                  SUM(total_amount) AS total
             FROM orders
            WHERE DATE(order_date) >= ?
            GROUP BY DATE(order_date)
            ORDER BY day""",
        (week_ago,),
    )

    low_stock = query(
        """SELECT * FROM products
            WHERE stock <= ? AND status != 'hidden'
            ORDER BY stock ASC, name""",
        (get_store_settings().low_stock_limit,),
    )

    upcoming = query(
        """SELECT a.*, s.name AS service_name
             FROM appointments a
             JOIN services s ON s.service_id = a.service_id
            WHERE a.appt_date >= date('now', 'localtime')
              AND a.status = 'scheduled'
            ORDER BY a.appt_date, a.appt_time
            LIMIT 10"""
    )

    return render_template(
        "reports.html",
        user=user,
        active="reports",
        title="Reports",
        today_sales=today_sales,
        week_sales=week_sales,
        top_sellers=top_sellers,
        daily=daily,
        low_stock=low_stock,
        upcoming=upcoming,
        low_stock_limit=get_store_settings().low_stock_limit,
    )
