from __future__ import annotations

from ..config import CompanyConfig
from ..errors import SourceError
from ..http import HttpClient
from .base import SourceAdapter
from .eightfold import EightfoldApplyV2Adapter, EightfoldPCSXAdapter
from .html_sources import AvatureAdapter, RadancyJsonLdAdapter
from .simple import AmazonAdapter, AshbyAdapter, GreenhouseAdapter
from .versioned import MetaRelayAdapter, RipplingAdapter


_ADAPTERS: dict[str, type[SourceAdapter]] = {
    "amazon_jobs_json": AmazonAdapter,
    "avature_html": AvatureAdapter,
    "eightfold_pcsx_session": EightfoldPCSXAdapter,
    "greenhouse": GreenhouseAdapter,
    "ashby": AshbyAdapter,
    "radancy_html_jsonld": RadancyJsonLdAdapter,
    "meta_relay_jsonld": MetaRelayAdapter,
    "eightfold_apply_v2": EightfoldApplyV2Adapter,
    "rippling_algolia_next_data": RipplingAdapter,
}


def supported_adapters() -> set[str]:
    return set(_ADAPTERS)


def build_adapter(config: CompanyConfig, http: HttpClient) -> SourceAdapter:
    try:
        adapter_type = _ADAPTERS[config.adapter]
    except KeyError as exc:
        raise SourceError("configuration_drift", f"unknown adapter: {config.adapter}") from exc
    return adapter_type(config, http)
