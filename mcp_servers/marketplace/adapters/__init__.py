"""Marketplace adapters; the active one is chosen by configuration, not by code changes."""

import os
from typing import Any

from mcp_servers.marketplace.adapters.gigsim import GigSimMarketplace
from mcp_servers.marketplace.local_sample import LocalSampleMarketplace

MODES = ("sample", "gigsim")


def build_marketplace(mode: str | None = None) -> Any:
    selected = mode or os.environ.get("GIGBID_MARKETPLACE_MODE", "sample")
    if selected == "sample":
        return LocalSampleMarketplace()
    if selected == "gigsim":
        return GigSimMarketplace()
    raise ValueError(f"unknown marketplace mode {selected!r}; expected one of {MODES}")
