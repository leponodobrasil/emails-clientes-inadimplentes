from __future__ import annotations

from dagster import Definitions, job, op, schedule

from dagster_app.logic import execute_report_dispatch, should_send_today


@op
def dispatch_reports_op():
    return execute_report_dispatch()


@job
def report_dispatch_job():
    dispatch_reports_op()


def should_execute_daily_dispatch(_context):
    return should_send_today()


@schedule(
    job=report_dispatch_job,
    cron_schedule="0 8 * * *",
    execution_timezone="America/Sao_Paulo",
    name="report_dispatch_schedule",
    should_execute=should_execute_daily_dispatch,
)
def report_dispatch_schedule(_context):
    return {}


defs = Definitions(
    jobs=[report_dispatch_job],
    schedules=[report_dispatch_schedule],
)
