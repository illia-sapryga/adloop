"""Tests for asset-extension write tools (call/price/promotion/location/etc.).

Covers preview validation and the apply-layer mutate operations for the
asset-extension tools, including the campaign/ad-group/customer multi-scope
paths. All data here is synthetic — placeholder phone numbers (555-01xx),
placeholder business names, and example.com URLs.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.ads.googleads.client import GoogleAdsClient

from adloop.ads import write
from adloop.ads.client import GOOGLE_ADS_API_VERSION
from adloop.config import AdLoopConfig, AdsConfig, SafetyConfig
from adloop.safety import preview as preview_store


# ---------------------------------------------------------------------------
# Fakes — mirror the lightweight harness in tests/test_ads_write.py
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, resource_name: str = ""):
        self.resource_name = resource_name


class _FakeMutateOperationResponse:
    def __init__(self, response_type: str | None = None, resource_name: str = ""):
        self.asset_result = _FakeResult()
        self.campaign_asset_result = _FakeResult()
        self.ad_group_asset_result = _FakeResult()
        self.customer_asset_result = _FakeResult()
        if response_type:
            getattr(self, response_type).resource_name = resource_name


class _FakePathService:
    def __init__(self, prefix: str):
        self.prefix = prefix

    def campaign_path(self, customer_id: str, entity_id: str) -> str:
        return f"customers/{customer_id}/campaigns/{entity_id}"

    def ad_group_path(self, customer_id: str, entity_id: str) -> str:
        return f"customers/{customer_id}/adGroups/{entity_id}"

    def asset_path(self, customer_id: str, entity_id: str) -> str:
        return f"customers/{customer_id}/assets/{entity_id}"

    def conversion_action_path(self, customer_id: str, entity_id: str) -> str:
        return f"customers/{customer_id}/conversionActions/{entity_id}"


class _FakeGoogleAdsService(_FakePathService):
    def __init__(self, responses: list[_FakeMutateOperationResponse] | None = None):
        super().__init__("googleAds")
        self.operations = None
        self._responses = responses or []
        self.search_queries: list[str] = []
        self.search_rows: list[object] = []

    def mutate(self, customer_id: str, mutate_operations: list[object]) -> object:
        self.operations = mutate_operations
        return SimpleNamespace(mutate_operation_responses=self._responses)

    def search(self, customer_id: str, query: str) -> list[object]:
        self.search_queries.append(query)
        return self.search_rows


class _FakeCampaignCriterionService:
    def __init__(self):
        self.operations = None

    def mutate_campaign_criteria(
        self, customer_id: str, operations: list[object]
    ) -> object:
        self.operations = operations
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    resource_name=f"customers/{customer_id}/campaignCriteria/{i}"
                )
                for i, _ in enumerate(operations)
            ]
        )


class _FakeAssetService(_FakePathService):
    def __init__(self):
        super().__init__("assets")
        self.operations = None

    def mutate_assets(self, customer_id: str, operations: list[object]) -> object:
        self.operations = operations
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    resource_name=f"customers/{customer_id}/assets/{i}"
                )
                for i, _ in enumerate(operations)
            ]
        )


class _FakeLinkService:
    """Generic fake for CampaignAsset / CustomerAsset / AdGroupAsset services."""

    def __init__(self, prefix: str):
        self.prefix = prefix
        self.operations = None

    def _mutate(self, customer_id, operations):
        self.operations = operations
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    resource_name=f"customers/{customer_id}/{self.prefix}/{i}"
                )
                for i, _ in enumerate(operations)
            ]
        )

    mutate_campaign_assets = _mutate
    mutate_customer_assets = _mutate
    mutate_ad_group_assets = _mutate


class _FakeCustomerAssetService:
    def __init__(self):
        self.operations = None

    def mutate_customer_assets(
        self, customer_id: str, operations: list[object]
    ) -> object:
        self.operations = operations
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    resource_name=f"customers/{customer_id}/customerAssets/{i}"
                )
                for i, _ in enumerate(operations)
            ]
        )


class _FakeAssetSetService:
    def __init__(self):
        self.operations = None

    def mutate_asset_sets(self, customer_id: str, operations: list[object]) -> object:
        self.operations = operations
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    resource_name=f"customers/{customer_id}/assetSets/1"
                )
            ]
        )


class _FakeAssetSetLinkService:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.operations = None

    def _mutate(self, customer_id, operations):
        self.operations = operations
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    resource_name=f"customers/{customer_id}/{self.prefix}/1"
                )
            ]
        )

    mutate_customer_asset_sets = _mutate
    mutate_campaign_asset_sets = _mutate


class _FakeClient:
    def __init__(self, services: dict[str, object]):
        self._base = GoogleAdsClient(
            credentials=None,
            developer_token="test-token",
            use_proto_plus=True,
            version=GOOGLE_ADS_API_VERSION,
        )
        self.enums = self._base.enums
        self.get_type = self._base.get_type
        self._services = services

    def get_service(self, name: str) -> object:
        return self._services[name]


@pytest.fixture(autouse=True)
def clear_pending_plans():
    preview_store.set_plan_store(preview_store.InMemoryPlanStore())
    yield
    preview_store.set_plan_store(preview_store.InMemoryPlanStore())


@pytest.fixture
def config() -> AdLoopConfig:
    return AdLoopConfig(
        ads=AdsConfig(customer_id="123-456-7890"),
        safety=SafetyConfig(require_dry_run=True),
    )


def _asset_link_client(responses):
    google_ads_service = _FakeGoogleAdsService(responses)
    return google_ads_service, _FakeClient(
        {
            "GoogleAdsService": google_ads_service,
            "AssetService": _FakePathService("assets"),
            "CampaignService": _FakePathService("campaigns"),
            "ConversionActionService": _FakePathService("conversionActions"),
        }
    )


# ---------------------------------------------------------------------------
# Phone normalization
# ---------------------------------------------------------------------------


def test_normalize_phone_us_national():
    normalized, err = write._normalize_phone_e164("(555) 555-0142", "US")
    assert err is None
    assert normalized == "+15555550142"


def test_normalize_phone_strips_leading_country_code():
    normalized, err = write._normalize_phone_e164("1-555-555-0143", "US")
    assert err is None
    assert normalized == "+15555550143"


def test_normalize_phone_already_e164_passthrough():
    normalized, err = write._normalize_phone_e164("+445555550144", "GB")
    assert err is None
    assert normalized == "+445555550144"


def test_normalize_phone_strips_european_trunk_zero():
    normalized, err = write._normalize_phone_e164("020 5550 0145", "GB")
    assert err is None
    assert normalized == "+442055500145"


def test_normalize_phone_unknown_country_code_errors():
    normalized, err = write._normalize_phone_e164("5555550146", "ZZ")
    assert normalized == ""
    assert "dial-code map" in err


# ---------------------------------------------------------------------------
# draft_call_asset — preview + scope
# ---------------------------------------------------------------------------


def test_draft_call_asset_requires_phone(config):
    result = write.draft_call_asset(config, customer_id="123-456-7890")
    assert result["error"] == "phone_number is required"


def test_draft_call_asset_campaign_scope(config):
    result = write.draft_call_asset(
        config,
        customer_id="123-456-7890",
        phone_number="(555) 555-0142",
        campaign_id="1001",
    )
    assert result["operation"] == "create_call_asset"
    assert result["changes"]["scope"] == "campaign"
    assert result["changes"]["phone_number"] == "+15555550142"
    assert result["warnings"]


def test_draft_call_asset_ad_group_scope_wins(config):
    result = write.draft_call_asset(
        config,
        customer_id="123-456-7890",
        phone_number="+15555550142",
        campaign_id="1001",
        ad_group_id="2002",
    )
    assert result["changes"]["scope"] == "ad_group"
    assert result["entity_type"] == "ad_group_asset"
    assert result["entity_id"] == "2002"


def test_draft_call_asset_customer_scope_default(config):
    result = write.draft_call_asset(
        config,
        customer_id="123-456-7890",
        phone_number="+15555550142",
    )
    assert result["changes"]["scope"] == "customer"
    assert result["entity_type"] == "customer_asset"


def test_draft_call_asset_rejects_bad_schedule(config):
    result = write.draft_call_asset(
        config,
        customer_id="123-456-7890",
        phone_number="+15555550142",
        ad_schedule=[{"day_of_week": "FUNDAY", "start_hour": 9, "end_hour": 17}],
    )
    assert result["error"] == "Ad schedule validation failed"


def test_apply_create_call_asset_campaign_scope_links_call_field():
    responses = [
        _FakeMutateOperationResponse("asset_result", "customers/1234567890/assets/1"),
        _FakeMutateOperationResponse(
            "campaign_asset_result", "customers/1234567890/campaignAssets/1"
        ),
    ]
    google_ads_service, client = _asset_link_client(responses)

    write._apply_create_call_asset(
        client,
        "1234567890",
        {
            "scope": "campaign",
            "campaign_id": "1001",
            "ad_group_id": "",
            "phone_number": "+15555550142",
            "country_code": "US",
            "call_conversion_action_id": "",
            "ad_schedule": [],
        },
    )
    create = google_ads_service.operations[0].asset_operation.create
    assert create.call_asset.phone_number == "+15555550142"
    link = google_ads_service.operations[1].campaign_asset_operation.create
    assert link.field_type == client.enums.AssetFieldTypeEnum.CALL


def test_apply_create_call_asset_ad_group_scope_and_conversion_action():
    responses = [
        _FakeMutateOperationResponse("asset_result", "customers/1234567890/assets/1"),
        _FakeMutateOperationResponse(
            "ad_group_asset_result", "customers/1234567890/adGroupAssets/1"
        ),
    ]
    google_ads_service, client = _asset_link_client(responses)

    write._apply_create_call_asset(
        client,
        "1234567890",
        {
            "scope": "ad_group",
            "campaign_id": "",
            "ad_group_id": "2002",
            "phone_number": "+15555550142",
            "country_code": "US",
            "call_conversion_action_id": "555999",
            "ad_schedule": [
                {
                    "day_of_week": "MONDAY",
                    "start_hour": 9,
                    "start_minute": 0,
                    "end_hour": 17,
                    "end_minute": 30,
                }
            ],
        },
    )
    create = google_ads_service.operations[0].asset_operation.create
    assert create.call_asset.call_conversion_action.endswith("conversionActions/555999")
    assert (
        create.call_asset.call_conversion_reporting_state
        == client.enums.CallConversionReportingStateEnum.USE_RESOURCE_LEVEL_CALL_CONVERSION_ACTION
    )
    assert len(create.call_asset.ad_schedule_targets) == 1
    link = google_ads_service.operations[1].ad_group_asset_operation.create
    assert link.field_type == client.enums.AssetFieldTypeEnum.CALL


# ---------------------------------------------------------------------------
# add_ad_schedule
# ---------------------------------------------------------------------------


def test_add_ad_schedule_requires_campaign(config):
    result = write.add_ad_schedule(
        config,
        customer_id="123-456-7890",
        schedule=[{"day_of_week": "MONDAY", "start_hour": 9, "end_hour": 17}],
    )
    assert result["error"] == "campaign_id is required"


def test_add_ad_schedule_rejects_bad_minute(config):
    result = write.add_ad_schedule(
        config,
        customer_id="123-456-7890",
        campaign_id="1001",
        schedule=[
            {
                "day_of_week": "MONDAY",
                "start_hour": 9,
                "start_minute": 10,
                "end_hour": 17,
            }
        ],
    )
    assert result["error"] == "Validation failed"
    assert any("start_minute" in d for d in result["details"])


def test_add_ad_schedule_rejects_end_before_start(config):
    result = write.add_ad_schedule(
        config,
        customer_id="123-456-7890",
        campaign_id="1001",
        schedule=[
            {"day_of_week": "MONDAY", "start_hour": 17, "end_hour": 9}
        ],
    )
    assert result["error"] == "Validation failed"
    assert any("must be after" in d for d in result["details"])


def test_add_ad_schedule_preview_ok(config):
    result = write.add_ad_schedule(
        config,
        customer_id="123-456-7890",
        campaign_id="1001",
        schedule=[
            {
                "day_of_week": "monday",
                "start_hour": 9,
                "start_minute": 15,
                "end_hour": 17,
                "end_minute": 45,
            }
        ],
    )
    assert result["operation"] == "add_ad_schedule"
    assert result["changes"]["schedule"][0]["day_of_week"] == "MONDAY"


def test_apply_add_ad_schedule_builds_criteria():
    crit_service = _FakeCampaignCriterionService()
    client = _FakeClient(
        {
            "CampaignService": _FakePathService("campaigns"),
            "CampaignCriterionService": crit_service,
        }
    )
    result = write._apply_add_ad_schedule(
        client,
        "1234567890",
        {
            "campaign_id": "1001",
            "schedule": [
                {
                    "day_of_week": "MONDAY",
                    "start_hour": 9,
                    "start_minute": 0,
                    "end_hour": 17,
                    "end_minute": 0,
                }
            ],
        },
    )
    assert len(result["campaign_criteria"]) == 1
    crit = crit_service.operations[0].create
    assert crit.ad_schedule.day_of_week == client.enums.DayOfWeekEnum.MONDAY
    assert crit.ad_schedule.start_hour == 9
