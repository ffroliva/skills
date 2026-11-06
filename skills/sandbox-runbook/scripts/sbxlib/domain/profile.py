"""What each trust level may do. The fleet enforces this in code, before any box is created."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .trust import TrustLevel


class SecretPolicy(Enum):
    NONE = "none"
    CONFIGURED = "configured"  # only names the adoption file's allowed_secrets lists


class TemplatePolicy(Enum):
    STOCK_ONLY = "stock-only"  # a kit could mount or bake anything, and a pull request could change it
    ANY = "any"


class NetworkPolicy(Enum):
    DENY_BY_DEFAULT = "deny-by-default"  # the account's default must be deny-all, plus a named allow list
    ACCOUNT_DEFAULT = "account-default"


class OutputPolicy(Enum):
    RESULTS_ONLY = "results-only"  # rc and JUnit only, and whatever the box printed is shown as data
    EVERYTHING = "everything"


@dataclass(frozen=True)
class RunProfile:
    level: TrustLevel
    secrets: SecretPolicy
    templates: TemplatePolicy
    network: NetworkPolicy
    output: OutputPolicy
    max_ttl_minutes: int | None
    max_boxes: int | None


PROFILES = {
    TrustLevel.UNTRUSTED: RunProfile(TrustLevel.UNTRUSTED, SecretPolicy.NONE, TemplatePolicy.STOCK_ONLY,
                                     NetworkPolicy.DENY_BY_DEFAULT, OutputPolicy.RESULTS_ONLY, 30, 1),
    TrustLevel.TRUSTED: RunProfile(TrustLevel.TRUSTED, SecretPolicy.CONFIGURED, TemplatePolicy.ANY,
                                   NetworkPolicy.ACCOUNT_DEFAULT, OutputPolicy.EVERYTHING, None, None),
}
