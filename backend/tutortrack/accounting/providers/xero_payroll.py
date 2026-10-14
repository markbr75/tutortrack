"""Xero Payroll (UK, Payroll API 2.0) client (E23-T10, E12 FR-12-8 "sync via API").

Employed tutors' hours from an approved pay run become draft timesheets in Xero Payroll
(one per employee, lines per day against the mapped earnings rate), so the payroll
administrator runs payroll in Xero with them. It uses the organisation's Xero connection,
which needs the ``payroll.*`` scopes (reconnect Xero once to grant them).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, ClassVar, Protocol

from tutortrack.integrations.providers import Credentials, http

API = "https://api.xero.com/payroll.xro/2.0"
SCOPES = ("payroll.employees", "payroll.timesheets", "payroll.settings")


@dataclass(frozen=True)
class Employee:
    id: str
    email: str
    first_name: str = ""
    last_name: str = ""
    calendar_id: str = ""


@dataclass(frozen=True)
class EarningsRate:
    id: str
    name: str
    kind: str = ""  # OrdinaryEarnings, Overtime, ...


class PayrollClient(Protocol):
    def employees(self, creds: Credentials) -> list[Employee]: ...

    def earnings_rates(self, creds: Credentials) -> list[EarningsRate]: ...

    def push_timesheet(
        self,
        creds: Credentials,
        *,
        employee: Employee,
        start: str,
        end: str,
        lines: list[tuple[str, Decimal]],
        earnings_rate: str,
        idempotency_key: str,
    ) -> str: ...


class XeroPayrollClient:
    def _call(
        self, creds: Credentials, method: str, path: str, body: Any = None, key: str = ""
    ) -> Any:
        headers = {"Xero-tenant-id": creds.account_id}
        if key:
            headers["Idempotency-Key"] = key[:128]
        return http.request(
            method,
            f"{API}{path}",
            token=creds.access_token,
            json_body=body,
            headers=headers,
            user_url=True,
            provider="xero",
        ).json()

    def employees(self, creds: Credentials) -> list[Employee]:
        out = []
        page = 1
        while page < 20:
            body = self._call(creds, "GET", f"/Employees?page={page}")
            rows = body.get("employees") or []
            for e in rows:
                out.append(
                    Employee(
                        id=str(e.get("employeeID", "")),
                        email=str(e.get("email", "")).lower(),
                        first_name=str(e.get("firstName", "")),
                        last_name=str(e.get("lastName", "")),
                        calendar_id=str(e.get("payrollCalendarID", "")),
                    )
                )
            if len(rows) < 100:
                break
            page += 1
        return out

    def earnings_rates(self, creds: Credentials) -> list[EarningsRate]:
        body = self._call(creds, "GET", "/EarningsRates")
        return [
            EarningsRate(
                str(r.get("earningsRateID", "")),
                str(r.get("name", "")),
                str(r.get("earningsType", "")),
            )
            for r in body.get("earningsRates") or []
            if r.get("currentRecord", True)
        ]

    def push_timesheet(
        self,
        creds: Credentials,
        *,
        employee: Employee,
        start: str,
        end: str,
        lines: list[tuple[str, Decimal]],
        earnings_rate: str,
        idempotency_key: str,
    ) -> str:
        body = self._call(
            creds,
            "POST",
            "/Timesheets",
            {
                "payrollCalendarID": employee.calendar_id,
                "employeeID": employee.id,
                "startDate": start,
                "endDate": end,
                "timesheetLines": [
                    {"date": day, "earningsRateID": earnings_rate, "numberOfUnits": str(hours)}
                    for day, hours in lines
                ],
            },
            key=idempotency_key,
        )
        return str((body.get("timesheet") or {}).get("timesheetID", ""))


class FakeXeroPayroll:
    """In-memory Xero Payroll: a couple of employees and an ordinary-hours rate; pushed
    timesheets are kept by idempotency key."""

    employees_list: ClassVar[list[Employee]] = []
    timesheets: ClassVar[dict[str, dict[str, Any]]] = {}

    @classmethod
    def reset(cls, employees: list[Employee] | None = None) -> None:
        cls.employees_list = list(employees or [])
        cls.timesheets.clear()

    def employees(self, creds: Credentials) -> list[Employee]:
        return list(self.employees_list)

    def earnings_rates(self, creds: Credentials) -> list[EarningsRate]:
        return [
            EarningsRate("rate-ordinary", "Ordinary Hours", "OrdinaryEarnings"),
            EarningsRate("rate-overtime", "Overtime Hours", "OvertimeEarnings"),
        ]

    def push_timesheet(
        self,
        creds: Credentials,
        *,
        employee: Employee,
        start: str,
        end: str,
        lines: list[tuple[str, Decimal]],
        earnings_rate: str,
        idempotency_key: str,
    ) -> str:
        found = self.timesheets.get(idempotency_key)
        if found is not None:
            return str(found["id"])
        sheet_id = f"ts-{len(self.timesheets) + 1}"
        self.timesheets[idempotency_key] = {
            "id": sheet_id,
            "employee": employee.id,
            "start": start,
            "end": end,
            "lines": [(d, str(h)) for d, h in lines],
            "rate": earnings_rate,
        }
        return sheet_id
