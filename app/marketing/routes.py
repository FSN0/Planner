from datetime import datetime

from flask import render_template


def render_landing():
    return render_template(
        'marketing/landing.html',
        current_year=datetime.utcnow().year,
    )
