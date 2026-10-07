"""Remove the unconnected model cutover scaffold and single-connection restriction.

The project has not been released. This is a one-way schema cleanup; restoring
the abandoned alternative requires restoring an isolated database snapshot.
"""

import hashlib
import json
from datetime import date
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20261007_0084"
down_revision = "20261007_0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    for table in ("production_experiments", "shot_experiments"):
        if connection.execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM {table})")).scalar():
            raise RuntimeError("Archive old experiment data and use a fresh development database")
    op.alter_column(
        "shot_reference_bindings",
        "shot_experiment_id",
        new_column_name="experiment_branch_id",
    )
    op.drop_table("shot_experiments")
    op.drop_table("production_experiments")
    op.drop_constraint("uq_provider_connection_profile", "provider_connections", type_="unique")
    op.drop_constraint("ck_provider_model_binding_target", "provider_model_bindings", type_="check")
    for column in (
        "binding_target_kind",
        "canonical_model_id",
        "model_capability_revision_id",
        "connection_discovered_model_id",
        "connection_model_capability_revision_id",
    ):
        op.drop_column("provider_model_bindings", column)
    for table in [
        "product_policy_events",
        "product_policy_states",
        "product_policy_revisions",
        "connection_model_capability_revisions",
        "connection_discovered_models",
        "model_publication_events",
        "model_publication_states",
        "model_capability_revisions",
        "runtime_handler_revisions",
        "protocol_contract_revisions",
    ]:
        op.drop_table(table)

    connection = op.get_bind()
    for manifest in json.loads(_CURRENT_CONTRACTS):
        body = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        connection.execute(
            sa.text(
                "UPDATE provider_model_catalog_entries SET lifecycle = 'retired' "
                "WHERE provider_type = :provider AND protocol_profile = :profile "
                "AND model_id = :model AND model_revision != :revision"
            ),
            {
                "provider": manifest["provider_type"],
                "profile": manifest["protocol_profile"],
                "model": manifest["model_id"],
                "revision": manifest["model_revision"],
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO provider_model_catalog_entries "
                "(id,provider_type,protocol_profile,model_id,model_revision,display_name,"
                "media_kind,lifecycle,catalog_source,capability_manifest_json,option_schema_json,"
                "documented_at,contract_manifest_hash) VALUES "
                "(:id,:provider,:profile,:model,:revision,:name,:media,:lifecycle,:source,"
                "CAST(:body AS json),CAST(:options AS json),CAST(:date AS date),:digest) "
                "ON CONFLICT (provider_type,protocol_profile,model_id,model_revision) DO NOTHING"
            ),
            {
                "id": str(uuid4()),
                "provider": manifest["provider_type"],
                "profile": manifest["protocol_profile"],
                "model": manifest["model_id"],
                "revision": manifest["model_revision"],
                "name": manifest["display_name"],
                "media": manifest["media_kind"],
                "lifecycle": manifest["lifecycle"],
                "source": manifest.get("catalog_source", "official_static"),
                "body": body,
                "options": json.dumps(manifest.get("option_schema", {})),
                "date": date.fromisoformat(manifest["documented_at"]),
                "digest": hashlib.sha256(body.encode()).hexdigest(),
            },
        )


def downgrade() -> None:
    raise RuntimeError("Single execution authority is irreversible; restore a database snapshot")


_CURRENT_CONTRACTS = r"""[
  {
    "manifest_version": "2026-08-19",
    "provider_type": "agnes",
    "protocol_profile": "agnes_cn_v1",
    "model_id": "agnes-image-2.1-flash",
    "model_revision": "v3",
    "media_kind": "image",
    "display_name": "Agnes Image Flash",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-08-19",
    "operations": {
      "image.generate": {
        "operation": "image.generate",
        "capabilities": [
          "image.t2i",
          "image.i2i"
        ],
        "output_constraints": {
          "size": "1K",
          "aspect_ratio": "9:16",
          "width": 736,
          "height": 1312,
          "response_format": "url"
        },
        "reference_constraints": {
          "reference_image": {
            "min": 0,
            "max": 1
          }
        },
        "exclusive_groups": []
      }
    },
    "option_schema": {
      "namespace": "",
      "options": {}
    },
    "implementation_status": "contract_tested",
    "evidence": {
      "current_contract": {
        "source_type": "contract_fixture",
        "source_url": "repository:backend/tests/unit",
        "checked_at": "2026-10-07"
      }
    }
  },
  {
    "manifest_version": "2026-08-10",
    "provider_type": "agnes",
    "protocol_profile": "agnes_cn_v1",
    "model_id": "agnes-video-v2.0",
    "model_revision": "v2",
    "media_kind": "video",
    "display_name": "Agnes Video V2.0",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-08-10",
    "operations": {
      "video.generate": {
        "operation": "video.generate",
        "capabilities": [
          "video.i2v.first_frame"
        ],
        "output_constraints": {
          "num_frames": {
            "allowed": [
              121
            ]
          },
          "frame_rate": {
            "allowed": [
              24
            ]
          },
          "height": 1280,
          "width": 720,
          "aspect_ratio": "9:16"
        },
        "reference_constraints": {
          "first_frame": {
            "min": 1,
            "max": 1
          }
        },
        "exclusive_groups": []
      }
    },
    "option_schema": {
      "namespace": "",
      "options": {}
    },
    "implementation_status": "contract_tested",
    "evidence": {
      "current_contract": {
        "source_type": "contract_fixture",
        "source_url": "repository:backend/tests/unit",
        "checked_at": "2026-10-07"
      }
    }
  },
  {
    "manifest_version": "2026-09-21",
    "provider_type": "agnes",
    "protocol_profile": "agnes_cn_v1",
    "model_id": "@contract/agnes-video-openai-async-v2",
    "model_revision": "v2",
    "media_kind": "video",
    "display_name": "Agnes Video 2.5 协议插件",
    "lifecycle": "active",
    "catalog_source": "protocol_contract",
    "documented_at": "2026-09-21",
    "operations": {
      "video.generate": {
        "operation": "video.generate",
        "capabilities": [
          "video.i2v.first_frame"
        ],
        "output_constraints": {
          "protocol_generation": "2.5",
          "resolution": "720P",
          "duration_seconds": 5,
          "aspect_ratio": "9:16",
          "native_audio": false
        },
        "reference_constraints": {
          "first_frame": {
            "min": 1,
            "max": 1
          }
        },
        "exclusive_groups": []
      }
    },
    "option_schema": {
      "namespace": "",
      "options": {}
    },
    "implementation_status": "contract_tested",
    "evidence": {
      "current_contract": {
        "source_type": "contract_fixture",
        "source_url": "repository:backend/tests/unit",
        "checked_at": "2026-10-07"
      }
    }
  },
  {
    "manifest_version": "2026-08-13",
    "provider_type": "minimax",
    "protocol_profile": "minimax_cn_v1",
    "model_id": "image-01",
    "model_revision": "v3",
    "media_kind": "image",
    "display_name": "MiniMax Image 01",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-08-13",
    "operations": {
      "image.generate": {
        "operation": "image.generate",
        "capabilities": [
          "image.i2i"
        ],
        "output_constraints": {
          "size": "1024x1024",
          "aspect_ratio": "1:1",
          "response_format": "url",
          "n": 1
        },
        "reference_constraints": {
          "reference_image": {
            "min": 1,
            "max": 1
          }
        },
        "exclusive_groups": []
      }
    },
    "option_schema": {
      "namespace": "",
      "options": {}
    },
    "implementation_status": "contract_tested",
    "evidence": {
      "current_contract": {
        "source_type": "contract_fixture",
        "source_url": "repository:backend/tests/unit",
        "checked_at": "2026-10-07"
      }
    }
  },
  {
    "manifest_version": "2026-09-29",
    "provider_type": "minimax",
    "protocol_profile": "minimax_cn_v1",
    "model_id": "MiniMax-H3",
    "model_revision": "v4",
    "media_kind": "video",
    "display_name": "MiniMax H3",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-09-29",
    "operations": {
      "video.generate": {
        "operation": "video.generate",
        "capabilities": [
          "video.i2v.first_frame",
          "video.t2v"
        ],
        "output_constraints": {
          "modes": {
            "first_frame": {
              "resolution": "768P",
              "duration_seconds": 5,
              "aspect_ratio": "adaptive",
              "native_audio": false
            },
            "text_to_video": {
              "resolution": "2K",
              "duration_seconds": 5,
              "aspect_ratio": {
                "allowed": [
                  "9:16",
                  "16:9"
                ]
              },
              "native_audio": true
            }
          }
        },
        "reference_constraints": {
          "first_frame": {
            "min": 0,
            "max": 1
          }
        },
        "exclusive_groups": []
      }
    },
    "option_schema": {
      "namespace": "",
      "options": {}
    },
    "implementation_status": "contract_tested",
    "evidence": {
      "current_contract": {
        "source_type": "contract_fixture",
        "source_url": "repository:backend/tests/unit",
        "checked_at": "2026-10-07"
      }
    }
  },
  {
    "manifest_version": "2026-09-21",
    "provider_type": "openai_compatible_media",
    "protocol_profile": "openai_media_v1",
    "model_id": "@contract/openai-image-v1",
    "model_revision": "v2",
    "media_kind": "image",
    "display_name": "OpenAI 兼容图像协议",
    "lifecycle": "active",
    "catalog_source": "protocol_contract",
    "documented_at": "2026-09-21",
    "operations": {
      "image.generate": {
        "operation": "image.generate",
        "capabilities": [
          "image.t2i",
          "image.i2i"
        ],
        "output_constraints": {
          "response_format": "url",
          "size": "1024x1024"
        },
        "reference_constraints": {
          "reference_image": {
            "min": 0,
            "max": 1
          }
        },
        "exclusive_groups": []
      }
    },
    "option_schema": {
      "namespace": "",
      "options": {}
    },
    "implementation_status": "contract_tested",
    "evidence": {
      "current_contract": {
        "source_type": "contract_fixture",
        "source_url": "repository:backend/tests/unit",
        "checked_at": "2026-10-07"
      }
    }
  },
  {
    "manifest_version": "2026-09-21",
    "provider_type": "openai_compatible_media",
    "protocol_profile": "openai_media_v1",
    "model_id": "@contract/openai-video-v1",
    "model_revision": "v2",
    "media_kind": "video",
    "display_name": "OpenAI 兼容异步视频协议",
    "lifecycle": "active",
    "catalog_source": "protocol_contract",
    "documented_at": "2026-09-21",
    "operations": {
      "video.generate": {
        "operation": "video.generate",
        "capabilities": [
          "video.i2v.first_frame"
        ],
        "output_constraints": {
          "duration_seconds": 5,
          "resolution": "720x1280",
          "aspect_ratio": "9:16",
          "native_audio": false
        },
        "reference_constraints": {
          "first_frame": {
            "min": 1,
            "max": 1
          }
        },
        "exclusive_groups": []
      }
    },
    "option_schema": {
      "namespace": "",
      "options": {}
    },
    "implementation_status": "contract_tested",
    "evidence": {
      "current_contract": {
        "source_type": "contract_fixture",
        "source_url": "repository:backend/tests/unit",
        "checked_at": "2026-10-07"
      }
    }
  },
  {
    "manifest_version": "2026-09-29",
    "provider_type": "openai_compatible_media",
    "protocol_profile": "openai_media_v1",
    "model_id": "@contract/sglang-h3-t2v-v1",
    "model_revision": "v2",
    "media_kind": "video",
    "display_name": "SGLang H3 文生视频 (T2VA)",
    "lifecycle": "active",
    "catalog_source": "protocol_contract",
    "documented_at": "2026-09-29",
    "operations": {
      "video.generate": {
        "operation": "video.generate",
        "capabilities": [
          "video.t2v"
        ],
        "output_constraints": {
          "duration_seconds": 5,
          "native_audio": false
        },
        "reference_constraints": {},
        "exclusive_groups": []
      }
    },
    "option_schema": {
      "namespace": "",
      "options": {}
    },
    "implementation_status": "contract_tested",
    "evidence": {
      "current_contract": {
        "source_type": "contract_fixture",
        "source_url": "repository:backend/tests/unit",
        "checked_at": "2026-10-07"
      }
    }
  },
  {
    "manifest_version": "2026-09-30-ref2va-v2",
    "provider_type": "openai_compatible_media",
    "protocol_profile": "openai_media_v1",
    "model_id": "@contract/sglang-h3-ref2va-v1",
    "model_revision": "v3",
    "media_kind": "video",
    "display_name": "SGLang H3 多素材参考 (Ref2VA)",
    "lifecycle": "active",
    "catalog_source": "protocol_contract",
    "documented_at": "2026-09-30",
    "operations": {
      "video.generate": {
        "operation": "video.generate",
        "capabilities": [
          "video.reference.image",
          "video.reference.video",
          "video.reference.audio"
        ],
        "output_constraints": {
          "duration_seconds": 5,
          "aspect_ratio": {
            "allowed": [
              "9:16",
              "16:9"
            ]
          },
          "native_audio": true
        },
        "reference_constraints": {
          "reference_image": {
            "min": 0,
            "max": 9
          },
          "reference_video": {
            "min": 0,
            "max": 3
          },
          "reference_audio": {
            "min": 0,
            "max": 3
          }
        },
        "exclusive_groups": [
          {
            "name": "ref2va",
            "members": [
              [
                "reference_image",
                "reference_video",
                "reference_audio"
              ]
            ]
          }
        ],
        "reference_media_limits": {
          "maximum_files": 12,
          "durations": {
            "reference_video": {
              "minimum_seconds": 2,
              "maximum_seconds": 15,
              "total_maximum_seconds": 15
            },
            "reference_audio": {
              "minimum_seconds": 2,
              "maximum_seconds": 15,
              "total_maximum_seconds": 15
            }
          }
        }
      }
    },
    "option_schema": {
      "namespace": "",
      "options": {}
    },
    "implementation_status": "contract_tested",
    "evidence": {
      "current_contract": {
        "source_type": "contract_fixture",
        "source_url": "repository:backend/tests/unit",
        "checked_at": "2026-10-07"
      }
    }
  },
  {
    "manifest_version": "2026-09-30-fl2va",
    "provider_type": "openai_compatible_media",
    "protocol_profile": "openai_media_v1",
    "model_id": "@contract/sglang-h3-fl2va-v1",
    "model_revision": "v2",
    "media_kind": "video",
    "display_name": "SGLang H3 文生/首尾帧 (FL2VA)",
    "lifecycle": "active",
    "catalog_source": "protocol_contract",
    "documented_at": "2026-09-30",
    "operations": {
      "video.generate": {
        "operation": "video.generate",
        "capabilities": [
          "video.t2v",
          "video.i2v.first_frame",
          "video.i2v.last_frame"
        ],
        "output_constraints": {
          "modes": {
            "text_to_video": {
              "duration_seconds": 5,
              "aspect_ratio": {
                "allowed": [
                  "9:16",
                  "16:9"
                ]
              },
              "native_audio": true
            },
            "first_frame": {
              "duration_seconds": 5,
              "aspect_ratio": {
                "allowed": [
                  "9:16",
                  "16:9"
                ]
              },
              "native_audio": true
            },
            "last_frame": {
              "duration_seconds": 5,
              "aspect_ratio": {
                "allowed": [
                  "9:16",
                  "16:9"
                ]
              },
              "native_audio": true
            },
            "first_last_frame": {
              "duration_seconds": 5,
              "aspect_ratio": {
                "allowed": [
                  "9:16",
                  "16:9"
                ]
              },
              "native_audio": true
            }
          }
        },
        "reference_constraints": {
          "first_frame": {
            "min": 0,
            "max": 1
          },
          "last_frame": {
            "min": 0,
            "max": 1
          }
        },
        "exclusive_groups": []
      }
    },
    "option_schema": {
      "namespace": "",
      "options": {}
    },
    "implementation_status": "contract_tested",
    "evidence": {
      "current_contract": {
        "source_type": "contract_fixture",
        "source_url": "repository:backend/tests/unit",
        "checked_at": "2026-10-07"
      }
    }
  },
  {
    "manifest_version": "2026-08-10",
    "provider_type": "volcengine",
    "protocol_profile": "ark_cn_v1",
    "model_id": "doubao-seedream-4-0-250828",
    "model_revision": "v3",
    "media_kind": "image",
    "display_name": "Seedream 4.0",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-08-10",
    "operations": {
      "image.generate": {
        "operation": "image.generate",
        "capabilities": [
          "image.t2i",
          "image.i2i"
        ],
        "output_constraints": {
          "size": "2048x2048",
          "response_format": "url",
          "watermark": false
        },
        "reference_constraints": {
          "reference_image": {
            "min": 0,
            "max": 1
          }
        },
        "exclusive_groups": []
      }
    },
    "option_schema": {
      "namespace": "",
      "options": {}
    },
    "implementation_status": "contract_tested",
    "evidence": {
      "current_contract": {
        "source_type": "contract_fixture",
        "source_url": "repository:backend/tests/unit",
        "checked_at": "2026-10-07"
      }
    }
  },
  {
    "manifest_version": "2026-08-10",
    "provider_type": "volcengine",
    "protocol_profile": "ark_cn_v1",
    "model_id": "doubao-seedance-1-0-pro-250528",
    "model_revision": "v2",
    "media_kind": "video",
    "display_name": "Seedance 1.0 Pro",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-08-10",
    "operations": {
      "video.generate": {
        "operation": "video.generate",
        "capabilities": [
          "video.i2v.first_frame"
        ],
        "output_constraints": {},
        "reference_constraints": {
          "first_frame": {
            "min": 1,
            "max": 1
          }
        },
        "exclusive_groups": []
      }
    },
    "option_schema": {
      "namespace": "",
      "options": {}
    },
    "implementation_status": "contract_tested",
    "evidence": {
      "current_contract": {
        "source_type": "contract_fixture",
        "source_url": "repository:backend/tests/unit",
        "checked_at": "2026-10-07"
      }
    }
  },
  {
    "manifest_version": "2026-08-17",
    "provider_type": "volcengine",
    "protocol_profile": "ark_cn_v1",
    "model_id": "doubao-seedance-2-0-260128",
    "model_revision": "v3",
    "media_kind": "video",
    "display_name": "Seedance 2.0",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-08-17",
    "operations": {
      "video.generate": {
        "operation": "video.generate",
        "capabilities": [
          "video.i2v.first_frame"
        ],
        "output_constraints": {},
        "reference_constraints": {
          "first_frame": {
            "min": 1,
            "max": 1
          }
        },
        "exclusive_groups": []
      }
    },
    "option_schema": {
      "namespace": "",
      "options": {}
    },
    "implementation_status": "contract_tested",
    "evidence": {
      "current_contract": {
        "source_type": "contract_fixture",
        "source_url": "repository:backend/tests/unit",
        "checked_at": "2026-10-07"
      }
    }
  }
]"""
