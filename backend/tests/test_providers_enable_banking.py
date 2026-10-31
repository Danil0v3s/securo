"""Unit tests for the Enable Banking provider.

Covers: JWT signing/claims, transaction fingerprint stability, account-type
mapping, nested vs flat transaction page shapes, restricted-mode handling.
HTTP is mocked end-to-end via httpx.MockTransport.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from app.providers.base import (
    ProviderUserActionRequired,
    SessionExpiredError,
    mask_last4,
)
from app.providers.enable_banking import (
    DEFAULT_HISTORY_DAYS,
    FALLBACK_HISTORY_DAYS,
    EnableBankingProvider,
    _account_identifier,
    _card_balance,
    _map_cash_account_type,
    _txn_fingerprint,
)


def _rsa_pem() -> tuple[str, str]:
    """Generate an in-memory RSA keypair and return PEM-encoded (private, public)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


@pytest.fixture
def eb_keys(monkeypatch):
    """Configure EB env vars with a fresh keypair and reset the provider cache."""
    private_pem, public_pem = _rsa_pem()
    monkeypatch.setenv("ENABLE_BANKING_APP_ID", "test-app-id-123")
    monkeypatch.setenv("ENABLE_BANKING_PRIVATE_KEY", private_pem)
    # Ensure the inline key wins over any file path the host env may have set.
    monkeypatch.setenv("ENABLE_BANKING_PRIVATE_KEY_FILE", "")
    # Force settings re-read.
    from app.core.config import get_settings

    get_settings.cache_clear()
    EnableBankingProvider._cached_token = None
    EnableBankingProvider._cached_token_exp = 0.0
    EnableBankingProvider._cached_private_key = None
    yield public_pem
    get_settings.cache_clear()


# ----- JWT signing -----


def test_jwt_token_has_expected_claims_and_kid(eb_keys):
    public_pem = eb_keys
    token = EnableBankingProvider._jwt_token()

    header = jwt.get_unverified_header(token)
    assert header["alg"] == "RS256"
    assert header["kid"] == "test-app-id-123"
    assert header["typ"] == "JWT"

    claims = jwt.decode(
        token, public_pem, algorithms=["RS256"], audience="api.enablebanking.com"
    )
    assert claims["iss"] == "enablebanking.com"
    assert claims["aud"] == "api.enablebanking.com"
    assert isinstance(claims["iat"], int)
    assert isinstance(claims["exp"], int)
    # Expiry within the next hour.
    assert claims["exp"] - claims["iat"] <= 3600


def test_jwt_token_cached_across_calls(eb_keys):
    a = EnableBankingProvider._jwt_token()
    b = EnableBankingProvider._jwt_token()
    assert a == b


# ----- pure helpers -----


def test_cash_account_type_mapping():
    assert _map_cash_account_type("CACC") == "checking"
    assert _map_cash_account_type("SVGS") == "savings"
    assert _map_cash_account_type("CARD") == "credit_card"
    assert _map_cash_account_type("LOAN") == "checking"
    assert _map_cash_account_type(None) == "checking"
    assert _map_cash_account_type("UNKNOWN_TYPE") == "checking"


def test_txn_fingerprint_stable_for_same_payload():
    raw = {
        "transaction_amount": {"amount": "12.34", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "booking_date": "2026-05-20",
        "value_date": "2026-05-20",
        "remittance_information": ["Coffee shop"],
        "creditor_account": {"iban": "DE89370400440532013000"},
    }
    fp1 = _txn_fingerprint("acc-uid-1", raw)
    fp2 = _txn_fingerprint("acc-uid-1", dict(raw))
    assert fp1 == fp2
    assert len(fp1) == 32


def test_txn_fingerprint_differs_on_amount_change():
    base = {
        "transaction_amount": {"amount": "12.34", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "booking_date": "2026-05-20",
        "remittance_information": ["X"],
    }
    other = dict(base)
    other["transaction_amount"] = {"amount": "12.35", "currency": "EUR"}
    assert _txn_fingerprint("acc", base) != _txn_fingerprint("acc", other)


def test_txn_fingerprint_uses_counterparty_name_when_iban_is_missing():
    base = {
        "entry_reference": "0",
        "transaction_amount": {"amount": "12.34", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "booking_date": "2026-05-20",
        "remittance_information": [],
        "creditor": {"name": "Coffee Shop"},
    }
    other = {**base, "creditor": {"name": "Bakery"}}
    assert _txn_fingerprint("acc", base) != _txn_fingerprint("acc", other)


# ----- transaction date resolution (issue: ActivoBank card dates) -----


def test_build_transaction_prefers_transaction_date_over_booking():
    """ActivoBank cards stamp every entry's booking_date with the statement date
    and put the real purchase date in transaction_date. We must not collapse a
    whole statement onto the booking day."""
    provider = EnableBankingProvider()
    raw = {
        "transaction_amount": {"amount": "112.42", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "booking_date": "2026-08-08",   # statement/import date
        "value_date": None,
        "transaction_date": "2026-05-11",  # the real purchase date
        "remittance_information": ["COMPRA 6466 WWW.AMAZON"],
    }
    txn = provider._build_transaction("acc-uid", raw, "posted", "auto")
    assert txn is not None
    assert txn.date == date(2026, 5, 11)


def test_build_transaction_falls_back_to_booking_then_value():
    provider = EnableBankingProvider()
    # No transaction_date → booking_date is used (unchanged behaviour).
    booking_only = {
        "transaction_amount": {"amount": "5.00", "currency": "EUR"},
        "credit_debit_indicator": "CRDT",
        "booking_date": "2026-08-01",
    }
    assert provider._build_transaction("a", booking_only, "posted", "auto").date == date(2026, 8, 1)

    # Neither transaction_date nor booking_date → value_date is the last resort.
    value_only = {
        "transaction_amount": {"amount": "5.00", "currency": "EUR"},
        "credit_debit_indicator": "CRDT",
        "value_date": "2026-07-30",
    }
    assert provider._build_transaction("a", value_only, "posted", "auto").date == date(2026, 7, 30)


# ----- stable ids for positional references (issue: ActivoBank card duplicates) -----


def _card_entry(entry_reference: str, booking_date: str, **extra) -> dict:
    return {
        "entry_reference": entry_reference,
        "transaction_amount": {"amount": "90.00", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "status": "BOOK",
        "booking_date": booking_date,
        "transaction_date": "2026-10-20",
        "remittance_information": ["COMPRA 6466 ANTHROPIC CLAUDE SUB"],
        **extra,
    }


def test_build_transaction_keys_card_entry_on_its_own_id_not_its_position():
    """ActivoBank moves an entry along its list (and onto a new statement) between
    syncs, changing the reference's tail. The same purchase must keep one id."""
    provider = EnableBankingProvider()
    refs = [
        ("126102021341101                                00002", "2026-10-29"),
        ("126102021341101                                00001", "2026-10-30"),
        ("126102021341101 00020VIS4544962833527000126110100004", "2026-11-01"),
        ("126102021341101 00020VIS4544962833527000126110200004", "2026-11-02"),
    ]
    ids = {
        provider._build_transaction("card", _card_entry(ref, booked), "posted", "auto").external_id
        for ref, booked in refs
    }
    assert ids == {"126102021341101"}


def test_build_transaction_keeps_separate_card_entries_apart():
    provider = EnableBankingProvider()
    purchase = provider._build_transaction(
        "card", _card_entry("126102021341101                                00001", "2026-10-30"), "posted", "auto"
    )
    fee = provider._build_transaction(
        "card", _card_entry("126102021341102                                00002", "2026-10-30"), "posted", "auto"
    )
    assert purchase.external_id != fee.external_id


def test_build_transaction_imports_placeholder_card_entry_as_pending():
    """An entry without its own id yet (all zeros) gets an id that survives the
    daily booking-date and position changes, and lands as pending."""
    provider = EnableBankingProvider()
    first = provider._build_transaction(
        "card", _card_entry("000000000000001                                00008", "2026-10-30"), "posted", "auto"
    )
    later = provider._build_transaction(
        "card", _card_entry("000000000000001                                00011", "2026-10-31"), "posted", "auto"
    )
    assert first.status == later.status == "pending"
    assert first.external_id == later.external_id
    assert first.external_id != "000000000000001"


def test_build_transaction_keeps_other_entry_references_whole():
    provider = EnableBankingProvider()
    raw = _card_entry("2026103032026-10-30-10.12.19.401199", "2026-10-30")
    txn = provider._build_transaction("checking", raw, "posted", "auto")
    assert txn.external_id == "2026103032026-10-30-10.12.19.401199"
    assert txn.status == "posted"


# ----- credit-card balance derivation (issue: card shows full limit free) -----


def test_card_balance_derives_owed_from_authorised_minus_available():
    """A used card reports available (ITAV) + authorised limit (OTHR) while
    closing-booked (CLBD) is 0. Owed = limit − available, not 0."""
    balances = [
        {"balance_type": "ITAV", "balance_amount": {"amount": "3204.21", "currency": "EUR"}},
        {"balance_type": "OTHR", "balance_amount": {"amount": "5000", "currency": "EUR"}},
        {"balance_type": "CLBD", "balance_amount": {"amount": "0", "currency": "EUR"}},
    ]
    owed, limit, currency = _card_balance(balances)
    assert owed == Decimal("1795.79")
    assert limit == Decimal("5000")
    assert currency == "EUR"


def test_card_balance_returns_none_without_both_types():
    """Without both ITAV and OTHR we can't derive owed → caller falls back to
    the generic balance pick."""
    only_closing = [
        {"balance_type": "CLBD", "balance_amount": {"amount": "0", "currency": "EUR"}},
    ]
    assert _card_balance(only_closing) == (None, None, None)
    assert _card_balance([]) == (None, None, None)


# ----- HTTP-driven parsing via httpx.MockTransport -----


def _mock_eb_transport(handler):
    return httpx.MockTransport(handler)


def _patch_client(provider: EnableBankingProvider, handler):
    """Replace _client() so requests hit our MockTransport."""
    transport = _mock_eb_transport(handler)

    def fake_client():
        return httpx.AsyncClient(
            base_url="https://api.enablebanking.com",
            transport=transport,
            headers={"Authorization": "Bearer test-jwt"},
        )

    return patch.object(provider, "_client", side_effect=fake_client)


@pytest.mark.asyncio
async def test_list_institutions_maps_and_dedupes_countries(eb_keys):
    provider = EnableBankingProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/aspsps"
        return httpx.Response(
            200,
            json={
                "aspsps": [
                    {
                        "name": "Revolut",
                        "country": "DE",
                        "logo": "https://l/revolut.png",
                        "bic": "REVOLT21",
                        "psu_types": ["personal"],
                        "maximum_consent_validity": 15552000,
                    },
                    {"name": "Sparkasse", "country": "DE"},
                    {"name": "BNP Paribas", "country": "FR"},
                ]
            },
        )

    with _patch_client(provider, handler):
        data = await provider.list_institutions()

    assert data.countries == ["DE", "FR"]
    names = [(i.country, i.name) for i in data.institutions]
    assert ("DE", "Revolut") in names
    assert ("FR", "BNP Paribas") in names
    revolut = next(i for i in data.institutions if i.name == "Revolut")
    assert revolut.max_consent_days == 180
    assert revolut.psu_types == ["personal"]


@pytest.mark.asyncio
async def test_get_oauth_url_returns_consent_url(eb_keys):
    provider = EnableBankingProvider()
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth"
        body = request.read().decode()
        import json as _json

        captured.update(_json.loads(body))
        return httpx.Response(
            200,
            json={
                "url": "https://consent.enablebanking.com/abc",
                "authorization_id": "auth-1",
                "psu_id_hash": "hash-x",
            },
        )

    with _patch_client(provider, handler):
        url = await provider.get_oauth_url(
            "https://app.example.com/oauth/callback",
            "state-xyz",
            flow_params={"country": "de", "institution_name": "Revolut"},
        )
    assert url == "https://consent.enablebanking.com/abc"
    assert captured["aspsp"] == {"name": "Revolut", "country": "DE"}
    assert captured["redirect_url"] == "https://app.example.com/oauth/callback"
    assert captured["state"] == "state-xyz"
    assert captured["psu_type"] == "personal"
    assert "Z" in captured["access"]["valid_until"]


@pytest.mark.asyncio
async def test_get_oauth_url_rejects_missing_flow_params(eb_keys):
    provider = EnableBankingProvider()
    with pytest.raises(ValueError):
        await provider.get_oauth_url(
            "https://x/cb", "s", flow_params={"country": "DE"}
        )


@pytest.mark.asyncio
async def test_handle_oauth_callback_restricted_mode_raises(eb_keys):
    provider = EnableBankingProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sessions"
        return httpx.Response(
            200,
            json={
                "session_id": "sess-1",
                "accounts": None,
                "aspsp": {"name": "Revolut", "country": "DE"},
                "access": {"valid_until": "2026-12-01T00:00:00Z"},
            },
        )

    with _patch_client(provider, handler):
        with pytest.raises(ProviderUserActionRequired) as exc:
            await provider.handle_oauth_callback("code-abc")
    assert exc.value.code == "no_accounts_linked"


@pytest.mark.asyncio
async def test_handle_oauth_callback_builds_connection_data(eb_keys):
    provider = EnableBankingProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/sessions":
            return httpx.Response(
                200,
                json={
                    "session_id": "sess-2",
                    "accounts": [
                        {
                            "uid": "acc-uid-1",
                            "currency": "EUR",
                            "display_name": "Main",
                            "cash_account_type": "CACC",
                        }
                    ],
                    "aspsp": {"name": "Revolut", "country": "DE"},
                    "access": {"valid_until": "2026-12-01T00:00:00Z"},
                },
            )
        if path == "/accounts/acc-uid-1/balances":
            return httpx.Response(
                200,
                json={
                    "balances": [
                        {
                            "balance_type": "CLBD",
                            "balance_amount": {"amount": "123.45", "currency": "EUR"},
                        }
                    ]
                },
            )
        return httpx.Response(404)

    with _patch_client(provider, handler):
        conn = await provider.handle_oauth_callback("code-abc")
    assert conn.external_id == "sess-2"
    assert conn.institution_name == "Revolut"
    assert len(conn.accounts) == 1
    acc = conn.accounts[0]
    assert acc.external_id == "acc-uid-1"
    assert acc.type == "checking"
    assert acc.balance == Decimal("123.45")
    assert acc.currency == "EUR"
    # session_id must NOT appear in credentials in plaintext.
    assert "session_id_enc" in conn.credentials
    assert conn.credentials.get("session_id") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("reported", ["-250000.00", "250000.00"])
async def test_loan_account_keeps_the_bank_reported_balance(eb_keys, reported):
    """Sign normalization happens on storage, by the account's stored type
    (account_service._provider_to_internal_balance), not in the provider."""
    provider = EnableBankingProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/sessions":
            return httpx.Response(
                200,
                json={
                    "session_id": "sess-loan",
                    "accounts": [
                        {
                            "uid": "loan-uid-1",
                            "currency": "EUR",
                            "display_name": "Mortgage",
                            "cash_account_type": "LOAN",
                        }
                    ],
                    "aspsp": {"name": "ING", "country": "NL"},
                    "access": {"valid_until": "2026-12-01T00:00:00Z"},
                },
            )
        if path == "/accounts/loan-uid-1/balances":
            return httpx.Response(
                200,
                json={
                    "balances": [
                        {
                            "balance_type": "CLBD",
                            "balance_amount": {"amount": reported, "currency": "EUR"},
                        }
                    ]
                },
            )
        return httpx.Response(404)

    with _patch_client(provider, handler):
        conn = await provider.handle_oauth_callback("code-loan")
    acc = conn.accounts[0]
    # A LOAN account still maps to checking: loans on a bank connection are
    # not modelled yet. What matters here is that the provider passes the
    # reported balance through untouched, whatever the type.
    assert acc.type == "checking"
    assert acc.balance == Decimal(reported)


@pytest.mark.asyncio
async def test_get_transactions_parses_nested_and_flat_shapes(eb_keys):
    """Both `transactions:{booked,pending}` and flat list must produce the
    same internal TransactionData list."""
    provider = EnableBankingProvider()

    nested_page = {
        "transactions": {
            "booked": [
                {
                    "entry_reference": "ref-1",
                    "transaction_amount": {"amount": "10.00", "currency": "EUR"},
                    "credit_debit_indicator": "DBIT",
                    "booking_date": "2026-05-10",
                    "remittance_information": ["Groceries"],
                },
            ],
            "pending": [
                {
                    "transaction_amount": {"amount": "5.50", "currency": "EUR"},
                    "credit_debit_indicator": "CRDT",
                    "booking_date": "2026-05-11",
                    "remittance_information": ["Refund"],
                },
            ],
        },
        "continuation_key": "",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/accounts/acc-1/transactions"
        return httpx.Response(200, json=nested_page)

    credentials = {"session_id_enc": None, "session_id": "sess-x", "valid_until": "2099-01-01T00:00:00Z"}
    with _patch_client(provider, handler):
        nested = await provider.get_transactions(credentials, "acc-1", date(2026, 5, 1))

    assert len(nested) == 2
    debit = next(t for t in nested if t.type == "debit")
    assert debit.amount == Decimal("10.00")
    assert debit.status == "posted"
    assert debit.external_id == "ref-1"
    credit = next(t for t in nested if t.type == "credit")
    assert credit.status == "pending"

    flat_page = {
        "transactions": [
            {
                "status": "BOOK",
                "transaction_amount": {"amount": "10.00", "currency": "EUR"},
                "credit_debit_indicator": "DBIT",
                "booking_date": "2026-05-10",
                "remittance_information": ["Groceries"],
            },
            {
                "status": "PDNG",
                "transaction_amount": {"amount": "5.50", "currency": "EUR"},
                "credit_debit_indicator": "CRDT",
                "booking_date": "2026-05-11",
                "remittance_information": ["Refund"],
            },
        ],
        "continuation_key": "",
    }

    def handler2(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=flat_page)

    with _patch_client(provider, handler2):
        flat = await provider.get_transactions(credentials, "acc-1", date(2026, 5, 1))

    assert len(flat) == 2
    assert sorted(t.type for t in flat) == sorted(t.type for t in nested)
    assert {t.status for t in flat} == {"posted", "pending"}


@pytest.mark.asyncio
async def test_get_transactions_stops_on_repeated_continuation_key(eb_keys, caplog):
    """A provider cursor loop must not duplicate a page up to the safety cap."""
    provider = EnableBankingProvider()
    requests: list[httpx.Request] = []
    page = {
        "transactions": [
            {
                "entry_reference": "looped-tx-1",
                "status": "BOOK",
                "transaction_amount": {"amount": "10.00", "currency": "EUR"},
                "credit_debit_indicator": "DBIT",
                "booking_date": "2026-05-10",
            }
        ],
        "continuation_key": "cursor-a",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=page)

    credentials = {
        "session_id": "sess-x",
        "valid_until": "2099-01-01T00:00:00Z",
    }
    with _patch_client(provider, handler), caplog.at_level("WARNING"):
        transactions = await provider.get_transactions(
            credentials, "acc-1", date(2026, 5, 1)
        )

    assert len(requests) == 2
    assert requests[0].url.params.get("continuation_key") is None
    assert requests[1].url.params["continuation_key"] == "cursor-a"
    assert [transaction.external_id for transaction in transactions] == ["looped-tx-1"]
    assert "pagination loop detected" in caplog.text


_WRONG_PERIOD_BODY = {
    "code": 422,
    "message": "Wrong transactions period requested",
    "detail": {"message": "Requested time period out of bound."},
    "error": "WRONG_TRANSACTIONS_PERIOD",
}
_CREDENTIALS = {"session_id": "sess-x", "valid_until": "2099-01-01T00:00:00Z"}


def _span_days(request: httpx.Request) -> int:
    """Inclusive number of days covered by a transactions request."""
    start = date.fromisoformat(request.url.params["date_from"])
    end = date.fromisoformat(request.url.params["date_to"])
    return (end - start).days + 1


@pytest.mark.asyncio
async def test_get_transactions_default_window_is_90_days_inclusive(eb_keys):
    provider = EnableBankingProvider()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"transactions": []})

    with _patch_client(provider, handler):
        await provider.get_transactions(_CREDENTIALS, "acc-1")

    assert len(requests) == 1
    assert requests[0].url.params["date_to"] == date.today().isoformat()
    assert _span_days(requests[0]) == DEFAULT_HISTORY_DAYS == 90


@pytest.mark.asyncio
async def test_get_transactions_retries_shorter_window_on_wrong_period(eb_keys):
    provider = EnableBankingProvider()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if _span_days(request) > FALLBACK_HISTORY_DAYS:
            return httpx.Response(422, json=_WRONG_PERIOD_BODY)
        return httpx.Response(
            200,
            json={
                "transactions": [
                    {
                        "entry_reference": "tx-1",
                        "status": "BOOK",
                        "transaction_amount": {"amount": "5.00", "currency": "EUR"},
                        "credit_debit_indicator": "DBIT",
                        "booking_date": date.today().isoformat(),
                    }
                ]
            },
        )

    with _patch_client(provider, handler):
        transactions = await provider.get_transactions(_CREDENTIALS, "acc-1")

    assert [_span_days(r) for r in requests] == [
        DEFAULT_HISTORY_DAYS,
        FALLBACK_HISTORY_DAYS,
    ]
    assert [t.external_id for t in transactions] == ["tx-1"]


@pytest.mark.asyncio
async def test_get_transactions_wrong_period_with_explicit_since_raises(eb_keys):
    """An explicit ``since`` is the caller's choice; never silently shorten it."""
    provider = EnableBankingProvider()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(422, json=_WRONG_PERIOD_BODY)

    with _patch_client(provider, handler), pytest.raises(httpx.HTTPStatusError):
        await provider.get_transactions(
            _CREDENTIALS, "acc-1", date.today() - timedelta(days=200)
        )

    assert len(requests) == 1


@pytest.mark.asyncio
async def test_get_transactions_other_422_is_not_retried(eb_keys):
    provider = EnableBankingProvider()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(422, json={"code": 422, "error": "SOMETHING_ELSE"})

    with _patch_client(provider, handler), pytest.raises(httpx.HTTPStatusError):
        await provider.get_transactions(_CREDENTIALS, "acc-1")

    assert len(requests) == 1


@pytest.mark.asyncio
async def test_refresh_credentials_expired_raises(eb_keys):
    provider = EnableBankingProvider()
    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace(
        "+00:00", "Z"
    )
    with pytest.raises(SessionExpiredError):
        await provider.refresh_credentials({"valid_until": expired})


@pytest.mark.asyncio
async def test_refresh_credentials_valid_passes(eb_keys):
    provider = EnableBankingProvider()
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat().replace(
        "+00:00", "Z"
    )
    creds = {"valid_until": future, "session_id_enc": "enc"}
    out = await provider.refresh_credentials(creds)
    assert out is creds


@pytest.mark.asyncio
async def test_get_accounts_raises_session_expired_when_details_unauthorized(eb_keys):
    """A 401 on one account's /details kills the whole consent, not just it.

    ``_request`` maps 401/410 to SessionExpiredError precisely because EB's
    access token is session-scoped: the consent is dead for every account. The
    per-account ``except httpx.HTTPError`` must not swallow it; doing so stored
    an empty account list and left the connection "active" (issue #1013).
    """
    provider = EnableBankingProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sessions/sess-x":
            return httpx.Response(200, json={
                "session_id": "sess-x",
                "accounts_data": [{"uid": "acc-1"}, {"uid": "acc-2"}],
            })
        # Anchored on purpose: ``endswith`` would also match a deeper path such
        # as /accounts/a/b/details, and ``.+`` in the middle matches it too.
        if re.fullmatch(r"/accounts/[^/]+/details", request.url.path):
            return httpx.Response(401, json={"code": 401, "error": "INVALID_TOKEN"})
        raise AssertionError(f"unexpected path {request.url.path}")

    with _patch_client(provider, handler):
        with pytest.raises(SessionExpiredError):
            await provider.get_accounts(_CREDENTIALS)


@pytest.mark.asyncio
async def test_get_accounts_exposes_stable_external_id(eb_keys):
    """EB's `uid` is session-scoped; `identification_hash` is the stable key.

    Reauthorising mints a new session, so the same real account comes back with
    a new uid. The hash is what survives that, and it already rides in the
    /sessions payload this method fetches. Carry it out on AccountData so the
    sync can re-match the existing row instead of creating a duplicate.
    """
    provider = EnableBankingProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/sessions/sess-x":
            return httpx.Response(200, json={
                "session_id": "sess-x",
                "accounts_data": [
                    {
                        "uid": "acc-1",
                        "identification_hash": "hash-1",
                        "identification_hashes": ["hash-1"],
                    },
                ],
            })
        if path == "/accounts/acc-1/details":
            return httpx.Response(200, json={
                "uid": "acc-1",
                "display_name": "Main",
                "currency": "EUR",
                "cash_account_type": "CACC",
            })
        if path == "/accounts/acc-1/balances":
            return httpx.Response(200, json={"balances": []})
        raise AssertionError(f"unexpected path {path}")

    with _patch_client(provider, handler):
        accounts = await provider.get_accounts(_CREDENTIALS)

    assert len(accounts) == 1
    assert accounts[0].external_id == "acc-1"
    assert accounts[0].stable_external_id == "hash-1"



# ----- account identifier / masking (issue #408) -----


def test_account_identifier_prefers_iban():
    raw = {
        "account_id": {"iban": "NL91ABNA0417164300", "other": {"identification": "999"}},
        "all_account_ids": [{"identification": "888", "scheme_name": "BBAN"}],
    }
    assert _account_identifier(raw) == "NL91ABNA0417164300"


def test_account_identifier_falls_back_to_other_scheme():
    """Banks outside SEPA report no IBAN; we must still find an identifier."""
    raw = {"account_id": {"other": {"identification": "12345678", "scheme_name": "BBAN"}}}
    assert _account_identifier(raw) == "12345678"


def test_account_identifier_falls_back_to_all_account_ids():
    raw = {"all_account_ids": [{"identification": "87654321", "scheme_name": "BBAN"}]}
    assert _account_identifier(raw) == "87654321"


def test_account_identifier_returns_none_when_absent():
    assert _account_identifier({"uid": "abc", "product": "Girokonto"}) is None
    assert _account_identifier({"account_id": {}, "all_account_ids": []}) is None


def test_mask_last4_keeps_only_the_tail():
    # The whole point: the full IBAN never reaches the database.
    assert mask_last4("NL91ABNA0417164300") == "4300"


def test_mask_last4_ignores_separators():
    """IBANs are commonly formatted in groups of four."""
    assert mask_last4("NL91 ABNA 0417 1643 00") == "4300"
    assert mask_last4("1234-5678") == "5678"


def test_mask_last4_returns_none_when_unusable():
    assert mask_last4(None) is None
    assert mask_last4("") is None
    # Too short to mask: render nothing rather than a partial identifier.
    assert mask_last4("12") is None
    assert mask_last4("- -") is None


def test_mask_last4_handles_exactly_four():
    assert mask_last4("1234") == "1234"


# ----- counterparty fallback / transaction_date (issue #734, #753) -----


def test_build_transaction_description_falls_back_to_creditor_for_debit():
    provider = EnableBankingProvider()
    raw = {
        "transaction_amount": {"amount": "12.34", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "booking_date": "2026-08-20",
        "remittance_information": [],
        "creditor": {"name": "Example Merchant"},
    }
    tx = provider._build_transaction("acc-1", raw, "posted", "auto")
    assert tx is not None
    assert tx.description == "Example Merchant"


def test_build_transaction_description_falls_back_to_debtor_for_credit():
    provider = EnableBankingProvider()
    raw = {
        "transaction_amount": {"amount": "100.00", "currency": "EUR"},
        "credit_debit_indicator": "CRDT",
        "booking_date": "2026-08-20",
        "remittance_information": [],
        "debtor": {"name": "Employer Inc"},
    }
    tx = provider._build_transaction("acc-1", raw, "posted", "auto")
    assert tx is not None
    assert tx.description == "Employer Inc"


def test_build_transaction_description_prefers_remittance_over_counterparty():
    provider = EnableBankingProvider()
    raw = {
        "transaction_amount": {"amount": "15.00", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "booking_date": "2026-08-20",
        "remittance_information": ["Order #12345"],
        "creditor": {"name": "Example Merchant"},
    }
    tx = provider._build_transaction("acc-1", raw, "posted", "auto")
    assert tx is not None
    assert tx.description == "Order #12345"


def test_build_transaction_description_prefers_additional_information_over_counterparty():
    provider = EnableBankingProvider()
    raw = {
        "transaction_amount": {"amount": "15.00", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "booking_date": "2026-08-20",
        "remittance_information": [],
        "additional_information": "Invoice 987",
        "creditor": {"name": "Example Merchant"},
    }
    tx = provider._build_transaction("acc-1", raw, "posted", "auto")
    assert tx is not None
    assert tx.description == "Invoice 987"


def test_build_transaction_description_whitespace_additional_information_falls_back():
    provider = EnableBankingProvider()
    raw = {
        "transaction_amount": {"amount": "15.00", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "booking_date": "2026-08-20",
        "remittance_information": [],
        "additional_information": "   ",
        "creditor": {"name": "Example Merchant"},
    }
    tx = provider._build_transaction("acc-1", raw, "posted", "auto")
    assert tx is not None
    assert tx.description == "Example Merchant"


def test_build_transaction_description_falls_back_to_generic_transaction():
    provider = EnableBankingProvider()
    raw = {
        "transaction_amount": {"amount": "15.00", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "booking_date": "2026-08-20",
    }
    tx = provider._build_transaction("acc-1", raw, "posted", "auto")
    assert tx is not None
    assert tx.description == "Transaction"


def test_build_transaction_falls_back_to_transaction_date():
    provider = EnableBankingProvider()
    raw = {
        "transaction_amount": {"amount": "20.00", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "transaction_date": "2026-08-29",
        "creditor": {"name": "Coffee Shop"},
    }
    tx = provider._build_transaction("acc-1", raw, "pending", "auto")
    assert tx is not None
    assert tx.date == date(2026, 8, 29)
    assert tx.description == "Coffee Shop"


def test_build_transaction_ignores_non_string_transaction_date():
    provider = EnableBankingProvider()
    raw = {
        "transaction_amount": {"amount": "20.00", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "transaction_date": 20260829,
        "creditor": {"name": "Coffee Shop"},
    }
    assert provider._build_transaction("acc-1", raw, "pending", "auto") is None


def test_build_transaction_treats_entry_reference_zero_as_missing():
    provider = EnableBankingProvider()
    raw1 = {
        "entry_reference": "0",
        "transaction_amount": {"amount": "20.00", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "transaction_date": "2026-08-29",
        "creditor": {"name": "Coffee Shop"},
    }
    raw2 = {
        "entry_reference": "0",
        "transaction_amount": {"amount": "40.00", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "transaction_date": "2026-08-29",
        "creditor": {"name": "Bakery"},
    }
    tx1 = provider._build_transaction("acc-1", raw1, "pending", "auto")
    tx2 = provider._build_transaction("acc-1", raw2, "pending", "auto")
    assert tx1 is not None and tx2 is not None
    assert tx1.external_id != "0"
    assert tx2.external_id != "0"
    assert tx1.external_id != tx2.external_id


def test_txn_fingerprint_includes_transaction_date():
    raw1 = {
        "transaction_amount": {"amount": "20.00", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "transaction_date": "2026-08-29",
    }
    raw2 = {
        "transaction_amount": {"amount": "20.00", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "transaction_date": "2026-08-30",
    }
    fp1 = _txn_fingerprint("acc-1", raw1)
    fp2 = _txn_fingerprint("acc-1", raw2)
    assert fp1 != fp2




# ----- session status on sync -----


def _session_payload(status: str) -> dict:
    """GET /sessions/{id} as Enable Banking returns it (account uids only).

    `valid_until` is always in the future: the status alone must decide."""
    valid_until = (
        (datetime.now(timezone.utc) + timedelta(days=180))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return {
        "status": status,
        "accounts": ["acc-uid-1"],
        "accounts_data": [{"uid": "acc-uid-1", "identification_hash": "hash-1"}],
        "aspsp": {"name": "Openbank", "country": "ES"},
        "access": {"valid_until": valid_until},
    }


@pytest.mark.asyncio
async def test_get_accounts_raises_when_session_expired_at_bank(eb_keys):
    """The bank can end consent long before `valid_until`. EB then still
    answers GET /sessions with 200 but `status: EXPIRED`, and every account
    call fails with a 400 ASPSP_ERROR. That must surface as an expired
    session, not as a sync that silently finds no accounts."""
    provider = EnableBankingProvider()
    details_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sessions/sess-1":
            return httpx.Response(200, json=_session_payload("EXPIRED"))
        details_calls.append(request.url.path)
        return httpx.Response(
            400,
            json={
                "code": 400,
                "message": "Error interacting with ASPSP",
                "detail": {"message": "Unauthorized, authentication failure"},
                "error": "ASPSP_ERROR",
            },
        )

    with _patch_client(provider, handler):
        with pytest.raises(SessionExpiredError):
            await provider.get_accounts({"session_id": "sess-1"})
    assert details_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["REVOKED", "CLOSED", "CANCELLED", "INVALID"])
async def test_get_accounts_raises_for_other_terminal_session_states(eb_keys, status):
    provider = EnableBankingProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_session_payload(status))

    with _patch_client(provider, handler):
        with pytest.raises(SessionExpiredError):
            await provider.get_accounts({"session_id": "sess-1"})


@pytest.mark.asyncio
async def test_get_accounts_authorized_session_returns_accounts(eb_keys):
    provider = EnableBankingProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/sessions/sess-1":
            return httpx.Response(200, json=_session_payload("AUTHORIZED"))
        if path == "/accounts/acc-uid-1/details":
            return httpx.Response(
                200,
                json={
                    "uid": "acc-uid-1",
                    "name": "CUENTA CORRIENTE",
                    "currency": "EUR",
                    "cash_account_type": "CACC",
                    "account_id": {"iban": "ES0000000000000000001172"},
                },
            )
        if path == "/accounts/acc-uid-1/balances":
            return httpx.Response(
                200,
                json={"balances": [{
                    "balance_type": "CLBD",
                    "balance_amount": {"amount": "859.43", "currency": "EUR"},
                }]},
            )
        return httpx.Response(404)

    with _patch_client(provider, handler):
        accounts = await provider.get_accounts({"session_id": "sess-1"})
    assert [a.external_id for a in accounts] == ["acc-uid-1"]
    assert accounts[0].balance == Decimal("859.43")
