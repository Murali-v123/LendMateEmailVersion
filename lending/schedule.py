"""
Interest schedule rules shared by the ledger and the reminder engine.

Monthly loans accrue interest on each monthly due date (monthly_due_day,
clamped to the month's length).  Annual loans accrue on each anniversary of
the lending date.  Each due date closes an interest period that starts on
period_start(): the first of its month for monthly loans, one year earlier
for annual loans.
"""
import calendar
import datetime


def next_month_start(d):
    if d.month == 12:
        return datetime.date(d.year + 1, 1, 1)
    return datetime.date(d.year, d.month + 1, 1)


def anniversary(d, year):
    """The same month and day in `year`; 29 February falls back to 28 February."""
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


def one_year_before(d):
    return anniversary(d, d.year - 1)


def period_start(loan, due_date):
    if loan.interest_period == "monthly":
        return due_date.replace(day=1)
    return one_year_before(due_date)


def due_dates_through(loan, last_day):
    """
    Every interest due date for the loan on or after the lending date and on or
    before `last_day`, in date order.  Returns [] when the loan has no schedule.
    """
    lending = loan.lending_date
    if lending is None:
        return []

    dates = []
    if loan.interest_period == "monthly":
        if not loan.monthly_due_day:
            return []
        cur = lending.replace(day=1)
        while cur <= last_day:
            day = min(loan.monthly_due_day, calendar.monthrange(cur.year, cur.month)[1])
            due = datetime.date(cur.year, cur.month, day)
            if lending <= due <= last_day:
                dates.append(due)
            cur = next_month_start(cur)
    elif loan.interest_period == "annually":
        year = lending.year
        while True:
            due = anniversary(lending, year)
            if due > last_day:
                break
            if due > lending:
                dates.append(due)
            year += 1
    return dates
