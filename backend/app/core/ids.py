"""ID generation.

All surrogate primary keys are UUIDv7 (time-ordered) — see docs/schema.md.
Python gains uuid.uuid7() in 3.14 and PostgreSQL gains uuidv7() in 18; until
then this helper generates them.
"""

import os
import time
import uuid


def uuid7() -> str:
    """Return a new RFC 9562 UUIDv7 as a string.

    Layout: 48-bit Unix ms timestamp | version (7) | 12 random bits |
    variant (0b10) | 62 random bits. IDs sort by creation millisecond;
    order within the same millisecond is random.
    """
    ms = time.time_ns() // 1_000_000
    value = (ms & 0xFFFF_FFFF_FFFF) << 80 | int.from_bytes(os.urandom(10), "big")
    value = (value & ~(0xF << 76)) | (0x7 << 76)  # version
    value = (value & ~(0x3 << 62)) | (0x2 << 62)  # variant
    return str(uuid.UUID(int=value))
