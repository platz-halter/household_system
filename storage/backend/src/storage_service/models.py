import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db import Base


class QuantityType(str, enum.Enum):
    countable = "countable"
    uncountable = "uncountable"


class Location(Base):
    """A single cellar/household spot: room -> level -> shelf.

    Kept as its own table (rather than free-text fields on Item) so the
    filter dropdowns in the UI can list distinct known rooms/levels/shelves
    without scanning every item.
    """

    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("room", "level", "shelf", name="uq_location_triplet"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    room: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shelf: Mapped[str | None] = mapped_column(String(64), nullable=True)

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
