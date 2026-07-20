"""OpenAI text adapter. Real BYOK path is optional; default export is FakeOpenAIAdapter."""

from app.providers.fake import FakeOpenAIAdapter

OpenAIAdapter = FakeOpenAIAdapter
