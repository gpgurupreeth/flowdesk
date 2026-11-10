
"""Add user ownership and timestamps

Revision ID: e6ece7a3c403
Revises: 
Create Date: 2026-10-25 16:51:25.292581

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = 'e6ece7a3c403'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema with user ownership and timestamps.

    This migration is designed to be safe for existing data:
    1. Creates the users table
    2. Adds user_id as nullable to existing tables
    3. Creates a default migration user and backfills existing records
    4. Makes user_id NOT NULL and adds foreign keys
    5. Adds timestamp and deal_value columns
    6. Updates custom_field_definitions unique constraint to be user-scoped
    """
    # --- Step 1: Create users table ---
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=200), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)

    # --- Step 2: Add user_id as nullable to existing tables ---
    op.add_column('leads', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('custom_field_definitions',
                  sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('import_sessions',
                  sa.Column('user_id', sa.Integer(), nullable=True))

    # --- Step 3: Add other new columns ---
    op.add_column('leads', sa.Column('deal_value',
                                     sa.Numeric(precision=12, scale=2),
                                     nullable=True))
    op.add_column('leads', sa.Column('updated_at', sa.DateTime(timezone=True),
                                     server_default=sa.text('now()'),
                                     nullable=True))
    op.add_column('leads', sa.Column('imported_at', sa.DateTime(timezone=True),
                                     nullable=True))
    op.add_column('custom_field_definitions', sa.Column('created_at',
        sa.DateTime(timezone=True), server_default=sa.text('now()'),
        nullable=True))
    op.add_column('custom_field_definitions', sa.Column('updated_at',
        sa.DateTime(timezone=True), server_default=sa.text('now()'),
        nullable=True))

    # --- Step 4: Create a default migration user and backfill ---
    # We insert a system user that existing records will be assigned to.
    # The administrator should create real users and reassign records as needed.
    conn = op.get_bind()

    # Insert default user (hashed password is a placeholder; user must reset)
    default_user_email = "migration@flowdesk.local"
    default_user_name = "Migration Default User"
    default_hashed_password = "$2b$12$K.vZ3xR9Lq1Y2w3x4y5z6A7B8C9D0E1F2G3H4I5J6K7L8M9N0O1P2"

    result = conn.execute(
        text("""
            INSERT INTO users (full_name, email, hashed_password, is_active)
            VALUES (:name, :email, :password, true)
            RETURNING id
        """),
        {"name": default_user_name, "email": default_user_email,
         "password": default_hashed_password}
    )
    default_user_id = result.scalar()

    # Backfill existing records with the default user ID
    conn.execute(
        text("UPDATE leads SET user_id = :uid WHERE user_id IS NULL"),
        {"uid": default_user_id}
    )
    conn.execute(
        text("UPDATE custom_field_definitions SET user_id = :uid WHERE user_id IS NULL"),
        {"uid": default_user_id}
    )
    conn.execute(
        text("UPDATE import_sessions SET user_id = :uid WHERE user_id IS NULL"),
        {"uid": default_user_id}
    )

    # --- Step 5: Make user_id NOT NULL and add foreign keys ---
    op.alter_column('leads', 'user_id', nullable=False)
    op.alter_column('custom_field_definitions', 'user_id', nullable=False)
    op.alter_column('import_sessions', 'user_id', nullable=False)
    op.alter_column('leads', 'updated_at', nullable=False)
    op.alter_column('custom_field_definitions', 'created_at', nullable=False)
    op.alter_column('custom_field_definitions', 'updated_at', nullable=False)

    op.create_index(op.f('ix_leads_user_id'), 'leads', ['user_id'],
                    unique=False)
    op.create_foreign_key(
        'fk_leads_user_id', 'leads', 'users',
        ['user_id'], ['id'], ondelete='CASCADE'
    )

    op.create_index(op.f('ix_custom_field_definitions_user_id'),
                    'custom_field_definitions', ['user_id'], unique=False)
    op.create_foreign_key(
        'fk_custom_field_definitions_user_id',
        'custom_field_definitions', 'users',
        ['user_id'], ['id'], ondelete='CASCADE'
    )

    op.create_index(op.f('ix_import_sessions_user_id'),
                    'import_sessions', ['user_id'], unique=False)
    op.create_foreign_key(
        'fk_import_sessions_user_id',
        'import_sessions', 'users',
        ['user_id'], ['id'], ondelete='CASCADE'
    )

    # --- Step 6: Update custom_field_definitions unique constraint ---
    # Old: unique(name) globally
    # New: unique(user_id, name) - same name allowed for different users
    op.drop_constraint(
        'uq_custom_field_definitions_name',
        'custom_field_definitions',
        type_='unique'
    )
    op.create_unique_constraint(
        'uq_custom_field_definitions_name_user_id',
        'custom_field_definitions',
        ['user_id', 'name']
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Restore old unique constraint on custom_field_definitions
    op.drop_constraint(
        'uq_custom_field_definitions_name_user_id',
        'custom_field_definitions',
        type_='unique'
    )
    op.create_unique_constraint(
        'uq_custom_field_definitions_name',
        'custom_field_definitions',
        ['name'],
        postgresql_nulls_not_distinct=False
    )

    # Drop foreign keys and indexes
    op.drop_constraint('fk_import_sessions_user_id', 'import_sessions',
                       type_='foreignkey')
    op.drop_index(op.f('ix_import_sessions_user_id'), table_name='import_sessions')
    op.drop_column('import_sessions', 'user_id')

    op.drop_constraint('fk_custom_field_definitions_user_id',
                       'custom_field_definitions', type_='foreignkey')
    op.drop_index(op.f('ix_custom_field_definitions_user_id'),
                  table_name='custom_field_definitions')
    op.drop_column('custom_field_definitions', 'updated_at')
    op.drop_column('custom_field_definitions', 'created_at')
    op.drop_column('custom_field_definitions', 'user_id')

    op.drop_constraint('fk_leads_user_id', 'leads', type_='foreignkey')
    op.drop_index(op.f('ix_leads_user_id'), table_name='leads')
    op.drop_column('leads', 'imported_at')
    op.drop_column('leads', 'updated_at')
    op.drop_column('leads', 'deal_value')
    op.drop_column('leads', 'user_id')

    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
