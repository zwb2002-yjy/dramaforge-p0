"""Register the complete SQLAlchemy model graph for standalone processes."""

from __future__ import annotations


def load_all_models() -> None:
    """Import every ORM model module so cross-domain foreign keys can resolve."""
    from app.access import models as access_models
    from app.assets import models as assets_models
    from app.delivery import models as delivery_models
    from app.director import assistant_models as director_assistant_models
    from app.director import proposal_models as director_proposal_models
    from app.editing import models as editing_models
    from app.events import models as event_models
    from app.execution import models as execution_models
    from app.production import models as production_models
    from app.providers import catalog_models as provider_catalog_models
    from app.providers import models as provider_models
    from app.providers.model_profiles import orm as provider_profile_models
    from app.security import models as security_models

    _ = (
        access_models,
        assets_models,
        delivery_models,
        director_assistant_models,
        director_proposal_models,
        editing_models,
        event_models,
        execution_models,
        production_models,
        provider_catalog_models,
        provider_models,
        provider_profile_models,
        security_models,
    )
