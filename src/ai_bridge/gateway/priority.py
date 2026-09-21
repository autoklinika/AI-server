"""D.1 semantic admission contract; the scheduler still receives integers."""

from enum import StrEnum
from types import MappingProxyType


class PriorityClass(StrEnum):
    INFRASTRUCTURE = "infrastructure"
    INTERACTIVE_HIGH = "interactive-high"
    INTERACTIVE = "interactive"
    NORMAL = "normal"
    BACKGROUND = "background"
    MAINTENANCE = "maintenance"


PRIORITY_CLASS_DEFAULTS = MappingProxyType({
    PriorityClass.INFRASTRUCTURE: 10,
    PriorityClass.INTERACTIVE_HIGH: 25,
    PriorityClass.INTERACTIVE: 50,
    PriorityClass.NORMAL: 100,
    PriorityClass.BACKGROUND: 200,
    PriorityClass.MAINTENANCE: 300,
})


def priority_for_class(value: object) -> int:
    """Resolve an exact class name, including the historical critical alias."""
    if not isinstance(value, str):
        raise ValueError("invalid priority_class")
    if value == "critical":
        value = PriorityClass.INFRASTRUCTURE
    try:
        return PRIORITY_CLASS_DEFAULTS[PriorityClass(value)]
    except ValueError:
        # Do not echo arbitrary request content in validation errors.
        raise ValueError("invalid priority_class") from None
