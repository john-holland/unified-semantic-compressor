from __future__ import annotations

from typing import Protocol

from .types import (
    Bucket,
    ExtractedData,
    MinimizationContext,
    MinimizationResult,
    ScoredBucket,
    TokenizedData,
)


class ExtractAdapter(Protocol):
    def run(self, ctx: MinimizationContext) -> ExtractedData: ...


class TokenizeAdapter(Protocol):
    def run(self, ctx: MinimizationContext, extracted: ExtractedData) -> TokenizedData: ...


class BucketAdapter(Protocol):
    def run(self, ctx: MinimizationContext, extracted: ExtractedData, tokens: TokenizedData) -> list[Bucket]: ...


class ScoreAdapter(Protocol):
    def run(
        self,
        ctx: MinimizationContext,
        extracted: ExtractedData,
        tokens: TokenizedData,
        buckets: list[Bucket],
    ) -> list[ScoredBucket]: ...


class SelectAdapter(Protocol):
    def run(self, ctx: MinimizationContext, scored: list[ScoredBucket]) -> MinimizationResult: ...


class PersistAdapter(Protocol):
    def run(self, ctx: MinimizationContext, result: MinimizationResult) -> MinimizationResult: ...
