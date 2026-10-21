# Review of `planning/PLAN.md`

## Findings

1. **High: API contracts are explicitly deferred, which will cause frontend/backend drift.**  
   `PLAN.md:263` says request/response schemas and status codes will be detailed during implementation, but this plan is the shared contract for multiple agents. The frontend, backend, chat, and E2E agents need exact payloads, validation errors, and response shapes before implementation starts, especially for `/api/portfolio`, `/api/portfolio/trade`, `/api/watchlist`, `/api/chat`, and `/api/stream/prices`. Without those details, agents can build mutually incompatible types and tests. Add concrete JSON schemas, error status codes, and sample SSE events to the plan.

2. **High: Market data configuration is left open despite driving core behavior.**  
   `PLAN.md:155` leaves configuration names, defaults, and Massive tier-to-interval mapping undefined. This affects the background polling task, tests, Docker environment, and user documentation. The plan already specifies behavior such as 500ms simulator updates and Massive polling intervals, so it should define the actual env vars now, for example simulator interval, Massive poll interval, allowed ticker policy, and fallback/error behavior when Massive fails or rate-limits.

3. **High: The plan references a required `coreweave-interface` skill that is not available in this session.**  
   `PLAN.md:298` instructs implementers to use the `coreweave-interface` skill, but the available skills list does not include it. Agents following the plan may block or invent integration details. Replace this with repo-local LiteLLM/OpenRouter instructions, or add a planning note that the skill must be installed and document the fallback implementation path.

4. **Medium: The repository and plan are already out of sync on project structure.**  
   `PLAN.md:99` describes `frontend/`, `scripts/`, `test/`, `Dockerfile`, `docker-compose.yml`, and `.env.example`, but the current repo only has `backend/`, `planning/`, and top-level docs. The README also advertises these missing paths. This is manageable if the project is intentionally early-stage, but the plan should call out which directories are aspirational versus existing, or add a bootstrap milestone so agents know they are expected to create them.

5. **Medium: Static frontend serving is underspecified for a single-container build.**  
   `PLAN.md:410` says the static directory location is undecided. That decision affects the Dockerfile, FastAPI app setup, Next.js export config, SPA fallback routing, and cache behavior. Define the exported frontend path and FastAPI mount behavior before implementation.

6. **Medium: Mock LLM behavior is too narrow for reliable E2E coverage.**  
   `PLAN.md:358` says every mock chat response includes the same fixed trade. That makes it difficult to test watchlist changes, failed trades, sell flows, and no-action assistant replies. Use deterministic fixtures keyed by the user message, or provide a small mock scenario table so tests can cover all structured response branches without calling the real LLM.

7. **Low: Stop scripts removing the Docker image conflicts with fast iteration and idempotence.**  
   `PLAN.md:431` and `PLAN.md:434` say stop scripts remove the image. That makes repeated local runs slower and can surprise users who only expect the running container to stop. Consider making image removal opt-in via a flag such as `--remove-image`, while preserving the named volume by default.

## Open Questions

- What exact ticker validation source should the simulator use, and should unsupported tickers be rejected by a static allowlist, Massive lookup, or another mechanism?
- Should fractional shares have a minimum quantity or decimal precision limit?
- How much chat history should be loaded into the LLM prompt before context size becomes a problem?
- Should `/api/portfolio/history` be downsampled or limited by default once snapshots accumulate over multiple sessions?

## Summary

The plan is strong as a product vision and architecture outline, but it still leaves several cross-agent contracts undecided. The most important next step is to promote the deferred API, market-data, static-serving, and LLM mock details into explicit planning contracts before parallel implementation begins.
