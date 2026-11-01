"""Where providers come from: presets, discovery, and the model snapshot.

Kept apart from `nova/llm/providers/`, which is about wire protocols. Nothing
here talks to a model: it answers "what can be connected" and "what does it
serve", and both answers are data rather than configuration.

The two `load` functions would shadow each other here, so this module exposes
them under names that say which list they return.
"""

from nova.registry.catalogue import load as load_catalogue
from nova.registry.catalogue import record as record_catalogue
from nova.registry.discovery import DiscoveryError, discover_models, resolve_base_url
from nova.registry.presets import (
    BUNDLED,
    ProviderPreset,
    bundled_payload,
    remember,
    derive_from_catalog,
    set_candidates,
    load as load_presets,
    preset_for,
    preset_from_json,
    preset_ids,
)
from nova.registry.catalogue import refresh_models_dev as refresh_registry

__all__ = [
    "BUNDLED",
    "DiscoveryError",
    "ProviderPreset",
    "bundled_payload",
    "discover_models",
    "load_catalogue",
    "load_presets",
    "preset_for",
    "preset_from_json",
    "preset_ids",
    "derive_from_catalog",
    "remember",
    "set_candidates",
    "record_catalogue",
    "refresh_registry",
    "resolve_base_url",
]
