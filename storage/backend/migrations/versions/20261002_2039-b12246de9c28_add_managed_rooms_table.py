"""add managed rooms table

Revision ID: b12246de9c28
Revises: 7a61de3132a4
Create Date: 2026-10-02 20:39:52.125456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b12246de9c28'
down_revision: Union[str, Sequence[str], None] = '7a61de3132a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = "fk_locations_room_id_rooms"


def upgrade() -> None:
    """Upgrade schema.

    Autogenerate saw this as "add room_id NOT NULL" + "drop room", which
    would both (a) fail immediately against any existing locations row
    (NOT NULL column with no default/backfill — see MIGRATIONS.md) and
    (b) silently lose every existing room name. This hand-written version
    creates `rooms`, populates it from the distinct room values that
    already exist, backfills `room_id` from that, and only then tightens
    and drops the old column.
    """
    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rooms_name"), "rooms", ["name"], unique=True)

    # Nullable for now — populated below, tightened to NOT NULL afterward.
    op.add_column("locations", sa.Column("room_id", sa.Integer(), nullable=True))

    op.execute("INSERT INTO rooms (name) SELECT DISTINCT room FROM locations")
    op.execute(
        "UPDATE locations SET room_id = rooms.id "
        "FROM rooms WHERE rooms.name = locations.room"
    )

    op.alter_column("locations", "room_id", nullable=False)
    op.create_foreign_key(FK_NAME, "locations", "rooms", ["room_id"], ["id"])

    op.drop_index(op.f("ix_locations_room"), table_name="locations")
    op.drop_constraint(op.f("uq_location_triplet"), "locations", type_="unique")
    op.create_unique_constraint(
        "uq_location_triplet", "locations", ["room_id", "level", "shelf"]
    )
    op.create_index(
        op.f("ix_locations_room_id"), "locations", ["room_id"], unique=False
    )
    op.drop_column("locations", "room")


def downgrade() -> None:
    """Downgrade schema — reverses the data move as well as the shape."""
    op.add_column(
        "locations",
        sa.Column("room", sa.VARCHAR(length=64), autoincrement=False, nullable=True),
    )
    op.execute(
        "UPDATE locations SET room = rooms.name "
        "FROM rooms WHERE rooms.id = locations.room_id"
    )
    op.alter_column("locations", "room", nullable=False)

    op.drop_index(op.f("ix_locations_room_id"), table_name="locations")
    op.drop_constraint("uq_location_triplet", "locations", type_="unique")
    op.create_unique_constraint(
        op.f("uq_location_triplet"), "locations", ["room", "level", "shelf"]
    )
    op.create_index(op.f("ix_locations_room"), "locations", ["room"], unique=False)

    op.drop_constraint(FK_NAME, "locations", type_="foreignkey")
    op.drop_column("locations", "room_id")

    op.drop_index(op.f("ix_rooms_name"), table_name="rooms")
    op.drop_table("rooms")
