"""LiteLLM Gateway integration (spec §66–§70).

- :mod:`client` — HTTP gateway client (readiness / list_models / chat_completion)
- :mod:`errors` — classified gateway failures (ProviderErrorCode vocabulary)
- :mod:`metadata` — allowlisted response header parsing (cost / retry / latency)
- :mod:`model_catalog` — logical alias manifests + discovery sync

DramaForge never imports the ``litellm`` SDK (spec §128-1). The official
BerriAI/litellm Proxy is a separate runtime; this package talks to it over
OpenAI-compatible HTTP.
"""
