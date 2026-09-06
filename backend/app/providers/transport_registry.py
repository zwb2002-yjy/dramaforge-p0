"""V3 transport registry (spec §31).

Independent from the model registry: a TransportProfile is a wire protocol that
may be shared by many models (one OpenAI-compatible gateway profile, many
models), and one model may choose among profiles via its CapabilitySpec
``transport_profile_id``. Kept separate so protocol data never bloats the model
index.
"""

from __future__ import annotations

from app.providers.transport import TransportProfile


class DuplicateTransportError(ValueError):
    def __init__(self, profile_id: str) -> None:
        super().__init__(f"transport profile already registered: {profile_id}")


class UnknownTransportError(LookupError):
    def __init__(self, profile_id: str) -> None:
        super().__init__(f"unknown transport profile: {profile_id}")


class TransportRegistry:
    def __init__(self) -> None:
        self._profiles: dict[str, TransportProfile] = {}

    def register(self, profile: TransportProfile) -> None:
        if profile.id in self._profiles:
            raise DuplicateTransportError(profile.id)
        self._profiles[profile.id] = profile

    def get(self, profile_id: str) -> TransportProfile:
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise UnknownTransportError(profile_id)
        return profile

    def get_or_none(self, profile_id: str) -> TransportProfile | None:
        return self._profiles.get(profile_id)

    def list_profiles(self) -> list[TransportProfile]:
        return sorted(self._profiles.values(), key=lambda item: item.id)
