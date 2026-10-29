"""Pay-cycle reporting periods and the cash-only Balance Flow."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.transaction import Transaction
from app.services.dashboard_service import (
    _baseline_from_deltas,
    _cycle_start_day,
    _period_range,
    get_balance_history,
    get_summary,
)


async def _set_cycle(session: AsyncSession, user, day: int) -> None:
    user.preferences = {**(user.preferences or {}), "pay_cycle_start_day": day}
    await session.commit()


async def _account(
    session: AsyncSession, user, workspace, name: str, acc_type: str = "checking"
) -> Account:
    account = Account(
        id=uuid.uuid4(), user_id=user.id, workspace_id=workspace.id, name=name,
        type=acc_type, balance=Decimal("0"), currency="BRL",
    )
    session.add(account)
    await session.commit()
    return account


async def _txn(
    session: AsyncSession, user, account: Account, amount: float, txn_type: str, txn_date: date
) -> None:
    session.add(Transaction(
        id=uuid.uuid4(), user_id=user.id, account_id=account.id,
        description=f"{txn_type} {amount}", amount=Decimal(str(amount)),
        date=txn_date, type=txn_type, source="manual", currency="BRL",
        created_at=datetime.now(timezone.utc),
    ))
    await session.commit()


def test_period_range_without_cycle_is_the_calendar_month():
    assert _period_range(date(2026, 3, 1), None) == (date(2026, 3, 1), date(2026, 4, 1))


def test_period_range_runs_payday_to_payday():
    assert _period_range(date(2026, 11, 1), 25) == (date(2026, 10, 25), date(2026, 11, 25))


def test_period_range_for_january_starts_in_the_previous_december():
    assert _period_range(date(2027, 1, 1), 25) == (date(2026, 12, 25), date(2027, 1, 25))


@pytest.mark.parametrize(
    ("preferences", "expected"),
    [
        ({"pay_cycle_start_day": 25}, 25),
        ({"pay_cycle_start_day": 1}, 1),
        ({"pay_cycle_start_day": 28}, 28),
        ({"pay_cycle_start_day": 0}, None),
        ({"pay_cycle_start_day": 29}, None),
        ({"pay_cycle_start_day": True}, None),
        ({"pay_cycle_start_day": "25"}, None),
        ({}, None),
        (None, None),
    ],
)
def test_cycle_start_day_only_accepts_days_one_to_twenty_eight(preferences, expected):
    assert _cycle_start_day(SimpleNamespace(preferences=preferences)) == expected


def test_cycle_start_day_without_a_user_is_the_calendar_month():
    assert _cycle_start_day(None) is None


def test_baseline_aligns_pay_cycles_by_position():
    # September's cycle starts Aug 25 and October's starts Sep 25: the payday
    # of each cycle is position 1, whatever its calendar day.
    deltas = {date(2026, 8, 25): 100.0, date(2026, 9, 25): 300.0}

    baseline = _baseline_from_deltas(
        deltas, [date(2026, 9, 1), date(2026, 10, 1)], 31,
        today=date(2026, 12, 31), cycle_start_day=25,
    )

    assert baseline[0].median == 200.0


@pytest.mark.asyncio
async def test_summary_counts_an_end_of_month_salary_in_the_month_it_funds(
    session: AsyncSession, test_user, test_workspace, monkeypatch
):
    monkeypatch.setattr("app.services.dashboard_service.app_today", lambda: date(2026, 11, 30))
    await _set_cycle(session, test_user, 25)
    checking = await _account(session, test_user, test_workspace, "Salary account")
    await _txn(session, test_user, checking, 3000, "credit", date(2026, 10, 27))
    # After the next payday: December's cycle, not November's.
    await _txn(session, test_user, checking, 50, "debit", date(2026, 11, 26))

    summary = await get_summary(
        session, test_workspace.id, test_user.id, month=date(2026, 11, 1)
    )

    assert summary.pay_cycle_start_day == 25
    assert (summary.period_start, summary.period_end) == ("2026-10-25", "2026-11-24")
    assert summary.monthly_income == 3000
    assert summary.monthly_expenses == 0


@pytest.mark.asyncio
async def test_summary_without_a_cycle_reports_the_calendar_month(
    session: AsyncSession, test_user, test_workspace, monkeypatch
):
    monkeypatch.setattr("app.services.dashboard_service.app_today", lambda: date(2026, 11, 30))

    summary = await get_summary(
        session, test_workspace.id, test_user.id, month=date(2026, 11, 1)
    )

    assert summary.pay_cycle_start_day is None
    assert (summary.period_start, summary.period_end) == ("2026-11-01", "2026-11-30")


@pytest.mark.asyncio
async def test_balance_history_walks_the_pay_cycle_and_leaves_cards_out(
    session: AsyncSession, test_user, test_workspace, monkeypatch
):
    monkeypatch.setattr("app.services.dashboard_service.app_today", lambda: date(2026, 12, 31))
    await _set_cycle(session, test_user, 25)
    checking = await _account(session, test_user, test_workspace, "Cash")
    card = await _account(session, test_user, test_workspace, "Card", acc_type="credit_card")
    await _txn(session, test_user, checking, 200, "credit", date(2026, 9, 26))
    await _txn(session, test_user, checking, 1000, "credit", date(2026, 10, 25))
    await _txn(session, test_user, checking, 100, "debit", date(2026, 11, 24))
    await _txn(session, test_user, card, 500, "debit", date(2026, 11, 1))

    history = await get_balance_history(
        session, test_workspace.id, test_user.id,
        month=date(2026, 11, 1), comparison_months=[date(2026, 10, 1)],
    )

    # November's cycle: Oct 25 → Nov 24, one point per day, positions 1..31.
    assert len(history.current) == 31
    first, last = history.current[0], history.current[-1]
    assert (first.day, first.date, first.balance) == (1, "2026-10-25", 1200)
    # The card purchase is debt, not cash: only the checking debit moves the line.
    assert (last.day, last.date, last.balance) == (31, "2026-11-24", 1100)
    assert history.opening_balance == 200

    # October's cycle (Sep 25 → Oct 24) is the comparison, aligned by position.
    assert history.comparison is not None
    assert len(history.comparison) == 30
    assert (history.comparison[1].date, history.comparison[1].balance) == ("2026-09-26", 200)
