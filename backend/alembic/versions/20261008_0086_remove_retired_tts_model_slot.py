"""Remove the retired audio.tts model-profile binding.

Voice execution is owned by the explicit frozen voice_execution contract, not
the media/text model-profile resolver. Existing profile JSON may still contain
the old slot, so remove only that key while preserving every other binding.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0086"
down_revision = "20261007_0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE production_model_profiles
            SET bindings = ((bindings::jsonb - 'audio.tts')::json)
            WHERE bindings::jsonb ? 'audio.tts'
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError(
        "The retired audio.tts model slot has no canonical execution semantics; "
        "restore a database snapshot to downgrade"
    )
