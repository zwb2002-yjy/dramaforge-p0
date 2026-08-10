"""FROZEN seed snapshot for migration 20260810_0015. DO NOT EDIT.

This module mirrors app/providers/catalog_seed_data.py at migration time as
a self-contained literal snapshot. Historical migrations must never import
current runtime code: replaying history would otherwise depend on future edits.
Adding a model revision requires a NEW migration; never rewrite this file.

Tests assert hash_seed(FROZEN_0015[i]) equals the current catalog hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def hash_seed(manifest_dict: dict[str, Any]) -> str:
    """Stable canonical-JSON sha256 (duplicated here; frozen for this migration)."""
    raw = json.dumps(manifest_dict, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


FROZEN_0015 = [{'manifest_version': '2026-08-10',
  'provider_type': 'agnes',
  'protocol_profile': 'agnes_cn_v1',
  'model_id': 'agnes-image-2.1-flash',
  'model_revision': 'v1',
  'media_kind': 'image',
  'display_name': 'Agnes Image Flash',
  'lifecycle': 'active',
  'catalog_source': 'official_static',
  'documented_at': '2026-08-10',
  'operations': {'image.generate': {'operation': 'image.generate',
                                    'capabilities': ['image.t2i', 'image.i2i'],
                                    'output_constraints': {'size': '1024x768',
                                                           'response_format': 'url'},
                                    'reference_constraints': {'reference_image': {'min': 0,
                                                                                  'max': 1}},
                                    'exclusive_groups': []}},
  'option_schema': {'namespace': '', 'options': {}}},
 {'manifest_version': '2026-08-10',
  'provider_type': 'agnes',
  'protocol_profile': 'agnes_cn_v1',
  'model_id': 'agnes-video-v2.0',
  'model_revision': 'v1',
  'media_kind': 'video',
  'display_name': 'Agnes Video V2.0',
  'lifecycle': 'active',
  'catalog_source': 'official_static',
  'documented_at': '2026-08-10',
  'operations': {'video.generate': {'operation': 'video.generate',
                                    'capabilities': ['video.i2v'],
                                    'output_constraints': {'num_frames': {'allowed': [121]},
                                                           'frame_rate': {'allowed': [24]},
                                                           'height': 1280,
                                                           'width': 720,
                                                           'aspect_ratio': '9:16'},
                                    'reference_constraints': {'first_frame': {'min': 1, 'max': 1}},
                                    'exclusive_groups': []}},
  'option_schema': {'namespace': '', 'options': {}}},
 {'manifest_version': '2026-08-10',
  'provider_type': 'volcengine',
  'protocol_profile': 'ark_cn_v1',
  'model_id': 'doubao-seedream-4-0-250828',
  'model_revision': 'v1',
  'media_kind': 'image',
  'display_name': 'Seedream 4.0',
  'lifecycle': 'active',
  'catalog_source': 'official_static',
  'documented_at': '2026-08-10',
  'operations': {'image.generate': {'operation': 'image.generate',
                                    'capabilities': ['image.t2i', 'image.i2i'],
                                    'output_constraints': {'size': '2048x2048',
                                                           'response_format': 'url',
                                                           'watermark': False},
                                    'reference_constraints': {'reference_image': {'min': 0,
                                                                                  'max': 1}},
                                    'exclusive_groups': []}},
  'option_schema': {'namespace': '', 'options': {}}},
 {'manifest_version': '2026-08-10',
  'provider_type': 'volcengine',
  'protocol_profile': 'ark_cn_v1',
  'model_id': 'doubao-seedance-1-0-pro-250528',
  'model_revision': 'v1',
  'media_kind': 'video',
  'display_name': 'Seedance 1.0 Pro',
  'lifecycle': 'active',
  'catalog_source': 'official_static',
  'documented_at': '2026-08-10',
  'operations': {'video.generate': {'operation': 'video.generate',
                                    'capabilities': ['video.i2v'],
                                    'output_constraints': {},
                                    'reference_constraints': {'first_frame': {'min': 1, 'max': 1}},
                                    'exclusive_groups': []}},
  'option_schema': {'namespace': '', 'options': {}}}]
