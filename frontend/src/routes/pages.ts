import { lazyRouteComponent } from "@tanstack/react-router";

/**
 * Lazily imported route page components (V2 perf foundation).
 *
 * Each entry produces its own production chunk. Route definitions in
 * `routes/` keep their code-based identity, paths, params, and search
 * validation untouched; only their components are loaded on demand.
 */

export const LazyScriptWorkspace = lazyRouteComponent(
  () => import("../features/script/ScriptWorkspace"),
  "ScriptWorkspace",
);

export const LazyAssetCardsPanel = lazyRouteComponent(
  () => import("../features/assets/AssetCardsPanel"),
  "AssetCardsPanel",
);

export const LazySceneStoryboardWall = lazyRouteComponent(
  () => import("../features/scenes/SceneStoryboardWall"),
  "SceneStoryboardWall",
);

export const LazySceneWorkspace = lazyRouteComponent(
  () => import("../features/scenes/SceneWorkspace"),
  "SceneWorkspace",
);

export const LazyReviewWorkspace = lazyRouteComponent(
  () => import("../features/review/ReviewWorkspace"),
  "ReviewWorkspace",
);

export const LazyEditingWorkspace = lazyRouteComponent(
  () => import("../features/editing/EditingWorkspace"),
  "EditingWorkspace",
);

export const LazyProductionPage = lazyRouteComponent(
  () => import("./production-page"),
  "ProductionPage",
);

export const LazyDesignPreviewPage = lazyRouteComponent(
  () => import("./design-preview-page"),
  "DesignPreviewPage",
);
