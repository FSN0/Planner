from dataclasses import dataclass
from typing import Optional


class ExternalAuthDecision:
    VALID = 'valid'
    INVALID = 'invalid'
    UNAVAILABLE = 'unavailable'
    SKIPPED = 'skipped'


@dataclass
class ExternalAuthResult:
    decision: str
    provider: Optional[str] = None
    reason: Optional[str] = None
    status_code: Optional[int] = None
    detail: Optional[str] = None

    @property
    def is_valid(self):
        return self.decision == ExternalAuthDecision.VALID

    @property
    def is_invalid(self):
        return self.decision == ExternalAuthDecision.INVALID

    @property
    def is_unavailable(self):
        return self.decision == ExternalAuthDecision.UNAVAILABLE
