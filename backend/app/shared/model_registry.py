"""Register the complete SQLAlchemy model graph for standalone processes."""

from __future__ import annotations


def load_all_models() -> None:
    """Import every ORM model module so cross-domain foreign keys can resolve."""
    from app.access import models as access_models
    from app.assets import models as assets_models
    from app.creation import models as creation_models
    from app.delivery import models as delivery_models
    from app.events import models as event_models
    from app.execution import models as execution_models
    from app.production import models as production_models

    _ = (
        access_models,
        assets_models,
        creation_models,
        delivery_models,
        event_models,
        execution_models,
        production_models,
    )
