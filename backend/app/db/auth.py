import uuid

from sqlalchemy import Boolean, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, pg_enum
from app.db.enums import UserRole


class User(Base, TimestampMixin):
    """Unit 17a (MEADOWOPS-DOM-010): the two real accounts replacing the
    single shared Builder bearer token (PRD 5.1/8.4 amendment, DD-22).
    Still just two known users — no self-registration endpoint exists
    anywhere in this codebase; rows are created only by
    app.services.auth_seed.seed_initial_users.

    `email` is stored lowercased (enforced at the app layer, in
    app.services.auth_seed and app.api.auth, not by a DB constraint) so a
    case-difference can't produce two rows a human would consider the same
    account.
    """

    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
