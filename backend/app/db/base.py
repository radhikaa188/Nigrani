"""
SQLAlchemy Declarative Base definition for Nigrani platform database.
"""

from typing import Union
from sqlalchemy.orm import DeclarativeBase
import sqlalchemy.util.typing as _sa_typing

# Python 3.14 compatibility: Union.__getitem__(types) descriptor changed in 3.14.
# Union[types] is supported across all Python versions.
if hasattr(_sa_typing, "make_union_type"):
    try:
        _sa_typing.make_union_type(int, str)
    except TypeError:
        _sa_typing.make_union_type = lambda *types: Union[types]  # type: ignore[assignment]


class Base(DeclarativeBase):
    """Base class for all Nigrani database models."""

    pass
