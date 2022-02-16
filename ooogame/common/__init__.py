import enum

class PatchStatus(enum.Enum):
    SUBMITTED = 0
    ACCEPTED = 1
    TOO_MANY_BYTES = 2
    SLA_TIMEOUT = 3
    SLA_FAIL = 4
    TESTING_PATCH = 5
