"""Test-collection setup, not test cases.

household_service.crud imports household_service.reports, which creates
REPORTS_DIR (hardcoded to /app/data/reports, a path that only exists
inside the container) at *import time* — fine in production, fatal for
a plain `pytest` run on a dev machine. Stub it out before anything else
imports crud, so pure-function tests (crud.week_bounds, etc.) don't need
a container just to collect. Nothing here touches what actually runs in
production; the container never executes this file.
"""

import sys
import types

if "household_service.reports" not in sys.modules:
    stub = types.ModuleType("household_service.reports")
    stub.REPORTS_DIR = None
    stub.generate_report_pdf = lambda **_kwargs: "stubbed-report.pdf"
    sys.modules["household_service.reports"] = stub
