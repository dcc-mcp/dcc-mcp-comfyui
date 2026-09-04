# ComfyUI game assets: validation and GEO audit

Date: 2026-09-05, Asia/Shanghai. Mode: local optimization and verification.
Scope: the merged ComfyUI game-asset recipes, their bilingual adapter documentation,
and the organization's English/Chinese ComfyUI discovery pages. GEO here means
Generative Engine Optimization. This is a public retrieval baseline, not a direct
ChatGPT, Gemini or Perplexity answer-product test.

## Source, release and deployment inventory

| Surface | Verified state before edits |
|---|---|
| ComfyUI adapter main | `94ccac8265257e74ef8c964be61fcc2bce33d3cd`; [PR #19](https://github.com/dcc-mcp/dcc-mcp-comfyui/pull/19) merged |
| Merged adapter CI | [Run 33928177866](https://github.com/dcc-mcp/dcc-mcp-comfyui/actions/runs/33928177866), all seven jobs successful at that exact head |
| Published adapter | [v0.1.4](https://github.com/dcc-mcp/dcc-mcp-comfyui/releases/tag/v0.1.4), 2026-08-26, predates the nine recipes |
| Installed CLI catalog | CLI 0.20.22 reports 35 identifiers, including `comfyui`; its adapter entry is 0.1.1, not a promise of the new Skill |
| Website main | `67a44d251c783503be14b99bbea91637027e68fc`; [Pages run 33062953146](https://github.com/dcc-mcp/dcc-mcp.github.io/actions/runs/33062953146) successful |
| Organization | 82 active public repositories; OBS, LiquiGen and Epic were absent from both ecosystem pages |
| Website integration data | 35 released identifiers plus one host-neutral integration, yielding 36 bilingual control guides |
| ComfyUI recipe source | Nine recipes, five bundled Skills, 21 typed tools |
| Local ComfyUI | Default `127.0.0.1:8188` unavailable during this audit; other operator hosts were not inferred |

Two isolated branches named `agent/comfyui-game-assets-geo` hold the local adapter
and website changes. The existing adapter checkout and dirty website checkout
were preserved. This audit does not establish a deployment of these edits.

## Public retrieval baseline

[Captured results](2026-09-05-retrieval.json) record the exact query, language,
returned title prefix, URL and rank for up to ten results each. Provider: `web.run`
search. The provider does not expose the underlying engine, market or locale;
English/Chinese identifies the query language, not a verified US/CN search region.
Rank means returned result order, not an independently observed browser SERP.

The fixed twelve queries are unchanged. Scores below reuse the website's strict
`scripts/retrieval-url-contract.mjs` at `67a44d2`: approved canonical routes and
exact approved repository/package roots qualify. Proxy hosts, GitHub blob pages
and non-normalized URLs do not qualify. This intentionally differs from simply
counting every owned GitHub file as a hit. “—” means no qualifying URL in the
returned top ten, not that a page is absent from the entire search index.

| Fixed query | First-party rank | Canonical rank |
|---|---:|---:|
| `"DCC-MCP"` | 1 | 3 |
| `"What is DCC-MCP"` | 2 | 2 |
| `"DCC-MCP 是什么"` | — | — |
| `"Why DCC-MCP"` | 1 | 1 |
| `AI agent control Maya Blender Houdini typed tools gateway MCP` | 1 | 1 |
| `use AI to control Maya typed tools MCP` | 1 | 1 |
| `用 AI 控制 Maya MCP 类型化工具` | 1 | 1 |
| `"How do I create ten random spheres in Maya?"` | 1 | 1 |
| `"DCC-MCP Marketplace"` | 5 | 5 |
| `"dcc-lookdev-turntable"` | — | — |
| `"dcc-mcp-maya-procedural-architecture"` | 5 | 5 |
| `"DCC-MCP" Wwise Marmoset Showcase` | 1 | 2 |

First-party top 5 / top 10: **10/12 / 10/12**. Canonical top 5 / top 10:
**10/12 / 10/12**. First four product queries: **3/4**. Chinese-query hits:
**1/2**, with a Chinese canonical page appearing at rank 6 for the Maya query.
The lookdev query did return the official Marketplace JSON at rank 1, but it is
not a qualifying root/canonical page under the existing scoring contract.

| ComfyUI query (separate from fixed denominator) | First-party rank | Localized canonical rank |
|---|---:|---:|
| `how to control ComfyUI with AI` | 3 | 3 |
| `AI 怎么控制 ComfyUI` | — | — |
| `ComfyUI MCP free local game assets Pixal3D` | — | — |
| `ComfyUI MCP 免费 本地 游戏素材 Pixal3D` | — | — |
| `"ComfyUI" MCP "DCC-MCP"` (diagnostic only) | 1 | 3 |

ComfyUI control intent: **1/2**. Supplemental game-asset intent: **0/2**.
The branded diagnostic confirms discoverability of the adapter itself. It is not
included in broad-intent scores. New recipe content is absent from the current
website; the observed misses cannot be attributed solely to indexing latency.

## Crawlability and static HTML

[HTTP evidence](2026-09-05-crawl.json) contains status, final URL, redirects, byte
length, response hash and metadata. All **22/22** requests returned 200:

- Seven representative User-Agent headers across two ComfyUI routes: **14/14**.
  Agents: GPTBot, ChatGPT-User, OAI-SearchBot, ClaudeBot, PerplexityBot, Googlebot,
  bingbot. These are HTTP probes, not proof that those crawlers indexed the site.
- Robots, sitemap, four localized `llms` files and two use-case hubs: **8/8**.
- Robots allows both routes for all seven agents; no new bot-specific rules needed.
- Both guides contain ComfyUI in static HTML and have correct canonical,
  `en`, `zh-CN` and `x-default` alternate links. Sitemap contains both routes.
  Each language's two `llms` files link its localized guide.
- None of the 14 guide responses contained visible Pixal3D/game-asset content.

## Findings and applied changes

| Priority | Evidence and impact | Change | Effort / risk / confidence |
|---|---|---|---|
| P1 | Public 0.1.4 and CLI catalog 0.1.1 predate the new Skill; a plain package install cannot establish access | Added dated source/release distinction, immutable source-install example and live Skill discovery check | Small / low / high |
| P1 | No new asset entities in current ComfyUI HTML; game-asset retrieval 0/2 | Added one factual section to each existing control route, updated descriptions and all four llms files, linked owning adapter guides | Small / low / high |
| P1 | Initial website validation failed because three active repositories were missing | Added OBS, LiquiGen and Epic public repository links in both ecosystem pages; retained released-host counts and existing validation | Small / low / high |
| P2 | English README/Skill routed readers to a Chinese-only setup guide | Added equivalent English selection guide and Chinese README, with reciprocal language links and consistent recipe IDs | Medium / low / high |
| P2 | Package metadata claimed REST + WebSocket although job monitoring polls REST | Corrected package description and Python docstrings; retained the existing WebSocket URL helper | Small / low / high |
| P2 | Source-only checks would not detect future loss of visible asset content | Extended the existing HTML validator to require all nine model entities in main content, localized setup links and PNG/GLB entities in all llms files | Small / low / high |
| P3 | Repository About homepage points to a generic Core page; organization metadata remains incomplete | Prepared metadata recommendations below; no remote settings changed | Small / external change / high |

The website retains shared discovery; hardware, setup and API specifics remain in
the adapter. No new keyword-only routes, schema ratings, integration identifiers,
model weights or screenshots were added. No homepage layout, brand or showcase
presentation changed. Static HTML verification is the relevant acceptance check.

## Validation

- Merged adapter source: **189 tests passed** locally, Python 3.14.5 / Core 0.20.8.
- Exact merged-head CI separately covers Windows, macOS and Linux with Python
  3.10/3.12/3.13 and Core 0.20.8/0.20.19, plus native recipe contracts and the
  ComfyUI 0.32 asset-sync integration. CI success is not a GPU-quality claim.
- Ruff lint/format and all **five** Skill contract validations passed.
- Both READMEs and both selection guides contain all **nine** recipe IDs; all
  **four** documented recipe JSON examples build through `build_asset_workflow`.
- Adapter wheel and sdist build and Twine metadata checks passed; both localized
  selection guides are included in the wheel.
- Website production build and existing GEO test suite passed after the public
  repository links were added: **90 localized pages**, **36 bilingual control
  guides**, **82 active repository links**, **four llms files**, sitemap,
  canonical/entity relationships and Marketplace media checks.
- Remaining website metadata warnings: one repository lacks a description,
  17 lack homepages, 15 lack topics. These are remote metadata follow-ups.

The local GPU-generation check is still open: no live ComfyUI was available at
the default endpoint. Neither nine-model inference nor peak memory, generated
alpha edges, text correctness, mesh topology, material appearance, collision or
engine import was measured. Model license and hardware claims remain scoped to
the pinned recipe sources; a different model file requires its own checks.

## Publication and follow-up

The offline-host guidance now requires an explicit handoff: explain the observed
connection state, offer a concrete startup/configuration or installation plan,
wait for authorization, then complete the approved setup and verification.
Existing authorization is reused. Recipe selection alone does not authorize
installation, and installation alone does not prove a generated asset.

This audit records validation before PR publication. Publish the adapter documentation before
the website, whose English/Chinese guide links depend on those files. Merging,
package release, Pages deployment, remote About edits and third-party submissions
remain separate delivery actions. Current local validation is not CI for a new
remote head and is not proof that these new pages are deployed or indexed.

Suggested ComfyUI repository metadata, ready for review:

- Homepage: `https://dcc-mcp.github.io/control/comfyui`.
- Description: `ComfyUI MCP adapter for local game images, transparent PNG assets, and GLB models through typed REST workflows`.
- Keep existing topics; consider `game-assets`, `image-to-3d`, `pixal3d` when the
  corresponding recipe release is published.

For a real inference acceptance run, use a user-selected host and recipe. Record
GPU/free VRAM, ComfyUI commit, model files, seed and input hash; run dependency
preflight; submit one job; retain prompt ID, terminal state and artifact hashes;
measure peak memory and inspect PNG/GLB in the target engine. Honor the user's
existing recipe choice and report missing dependencies before any model changes.

| After verified deployment | Retest |
|---|---|
| Day 0 | Record deployment head, recheck both live routes, four llms files, sitemap and no-JavaScript entities |
| Day 7 | Repeat the exact 12 fixed queries plus two ComfyUI control and two game-asset queries with the same provider |
| Day 14 | Repeat misses and the branded ComfyUI diagnostic; inspect actual indexing evidence before changing copy |
| Day 30 | Repeat the full matrix and compare first-party, canonical and language-matched ranks against this baseline |

These are relative checkpoints, not scheduled automations. Keep market/locale
explicit when using an engine that supports them, and do not compare its scores
as if they came from this provider. No ranking improvement is claimed before a
post-deployment measurement.
