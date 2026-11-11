from dataclasses import dataclass
from enum import Enum

class State(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    MAINTENANCE = "MAINTENANCE"

class Operation(str, Enum):
    RESERVE = "RESERVE"
    CANCEL = "CANCEL"
    DEPOSIT = "DEPOSIT"
    RETRIEVE = "RETRIEVE"
    EXPIRE = "EXPIRE"
    DISABLE = "DISABLE"
    ENABLE = "ENABLE"
    INVALID_ACCESS = "INVALID_ACCESS"

@dataclass(frozen=True)
class Command:
    operation: Operation
    customer_id: str = "C1"
    code: str = ""
    expired: bool = False

@dataclass(frozen=True)
class Result:
    accepted: bool
    message: str

@dataclass
class Snapshot:
    state: State
    customer_id: str | None
    reservation_code: str | None
    retrieval_code: str | None
