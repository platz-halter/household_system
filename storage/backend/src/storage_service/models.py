import enum
from datetime import datetime

from shared.db import Base
from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship


class QuantityType(str, enum.Enum):
    countable = "countable"
    uncountable = "uncountable"


class Room(Base):
    """The managed list of valid rooms (Settings → Manage rooms). Items can
    only be placed in a room that exists here — free-typing a new room name
    on the item form was how the room filter dropdown ended up cluttered
    with near-duplicate/typo'd values, so creating a room is now its own
    explicit step."""

    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    locations: Mapped[list["Location"]] = relationship(back_populates="room")


class Location(Base):
    """A single cellar/household spot: room -> shelf -> shelf level.

    Kept as its own table (rather than free-text fields on Item) so the
    filter dropdowns in the UI can list distinct known shelves/levels
    without scanning every item. `level` is a shelf level (e.g. "top",
    "bottom shelf"), not a building floor.
    """

    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("room_id", "level", "shelf", name="uq_location_triplet"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shelf: Mapped[str | None] = mapped_column(String(64), nullable=True)

    room: Mapped[Room] = relationship(back_populates="locations")
    items: Mapped[list["Item"]] = relationship(back_populates="location")


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    quantity_type: Mapped[QuantityType] = mapped_column(
        Enum(QuantityType, name="quantity_type"), default=QuantityType.countable
    )
    # Only meaningful when quantity_type == countable.
    quantity: Mapped[int | None] = mapped_column(nullable=True)
    # Free-text amount for uncountable items (e.g. "half bag", "~2L left").
    # Only meaningful when quantity_type == uncountable.
    quantity_note: Mapped[str | None] = mapped_column(String(120), nullable=True)

    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id"), nullable=True
    )
    location: Mapped[Location | None] = relationship(back_populates="items")

    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    aliases: Mapped[list["ItemAlias"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class ItemAlias(Base):
    __tablename__ = "item_aliases"
    __table_args__ = (UniqueConstraint("item_id", "alias", name="uq_item_alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(String(200), index=True)

    item: Mapped[Item] = relationship(back_populates="aliases")
