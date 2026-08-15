# The Adventure Backend Architecture Draft

## 1. Purpose

The backend has one core responsibility: turn a player theme into a complete branching story tree, persist that tree, and expose it through a small job-driven REST API that the frontend can poll safely.

The current backend architecture is intentionally simple:

- FastAPI handles HTTP routing.
- SQLAlchemy persists jobs, stories, and story nodes.
- Gemini generates the entire story tree in a single structured response.
- A background task isolates the long-running generation step from the request/response cycle.

## 2. Core Backend Modules

### `main.py`

Application entry point. It:

- creates database tables on startup,
- configures CORS,
- mounts the story and job routers under `settings.API_PREFIX`.

### `routers/story.py`

Owns the story-generation lifecycle:

- accepts story creation requests,
- creates a `StoryJob`,
- attaches or creates the browser session cookie,
- starts background generation,
- exposes the endpoint for fetching the fully assembled story tree.

### `routers/job.py`

Owns read access to job status so the frontend can poll progress without blocking on the LLM call.

### `core/story_generator.py`

Owns provider-specific generation logic. This is where:

- the Gemini client is created,
- the story prompt and schema are sent,
- the structured response is validated,
- the nested story tree is flattened into relational rows.

### `core/models.py`

Defines the LLM-facing schema. This is the contract between the app and Gemini:

- `StoryLLMResponse` is the full top-level output,
- `StoryNodeLLM` is a recursive story node,
- `StoryOptionLLM` links a choice to its next node.

### `models/story.py`

Defines persistence for finished stories:

- `Story` is one generated adventure,
- `StoryNode` is one node in the tree.

### `models/job.py`

Defines persistence for in-flight and completed generation jobs.

### `schemas/*.py`

Defines HTTP request/response shapes for the frontend.

## 3. Story Generation Request Flow

### Step 1: frontend submits a theme

The frontend calls:

- `POST /api/stories/create`

Payload:

```json
{
  "theme": "pirates"
}
```

### Step 2: backend resolves the session

`get_session_id()` checks the `session_id` cookie:

- if present, reuse it,
- if missing, create a new UUID.

That session ID becomes the lightweight identity for the player. There is no auth layer yet.

### Step 3: backend creates a job row

`create_story()` creates a `StoryJob` with:

- `job_id`: public UUID used by the frontend,
- `session_id`: ties the job to the browser session,
- `theme`: the prompt input,
- `status="pending"`.

This is committed before story generation starts, which means the client immediately gets a durable handle it can poll.

### Step 4: backend returns immediately

The API returns the job object instead of waiting for Gemini. This avoids:

- request timeouts,
- blocking the UI,
- tying story generation latency to one HTTP request.

### Step 5: background task starts generation

FastAPI `BackgroundTasks` triggers `generate_story_task(job_id, theme, session_id)`.

Inside that function:

1. a new DB session is opened with `SessionLocal()`,
2. the job row is looked up by `job_id`,
3. the job moves from `pending` to `processing`,
4. Gemini is called,
5. the generated story is stored,
6. the job is marked `completed` or `failed`.

## 4. How Story Generation Works Internally

### Gemini call shape

`StoryGenerator.generate_story()` sends Gemini:

- a system instruction describing the branching-story requirements,
- a user instruction containing the chosen theme,
- a strict response schema using `StoryLLMResponse`,
- `thinking_level=medium`,
- the model `gemini-3.1-flash-lite`.

This is important structurally because the backend is not generating nodes incrementally. It expects one complete story tree in a single model response.

### Structured output contract

Gemini returns a validated object shaped like:

```json
{
  "title": "Story Title",
  "rootNode": {
    "content": "...",
    "isEnding": false,
    "isWinningEnding": false,
    "options": [
      {
        "text": "Choice A",
        "nextNode": {
          "...": "..."
        }
      }
    ]
  }
}
```

That response is not stored as raw JSON. Instead, the backend transforms it into relational records.

## 5. How Each Story Is Tracked

There are two separate tracking concepts:

### A. `StoryJob` tracks generation state

`StoryJob` answers: "What happened to the request to create a story?"

Fields and meaning:

- `job_id`: stable public identifier used by the frontend.
- `session_id`: identifies the browser/user instance that created the request.
- `theme`: the requested theme.
- `status`: `pending`, `processing`, `completed`, or `failed`.
- `story_id`: nullable until generation succeeds.
- `error`: nullable, filled when generation fails.
- `created_at`: when the request was accepted.
- `completed_at`: when generation finished or failed.

### B. `Story` tracks the finished adventure itself

`Story` answers: "What full adventure was generated?"

Fields and meaning:

- `id`: internal primary key.
- `title`: generated title.
- `session_id`: browser session that owns/created the story.
- `created_at`: when the story row was created.

### C. `StoryNode` tracks the tree structure

Each story is decomposed into many `StoryNode` rows.

Fields and meaning:

- `id`: node primary key.
- `story_id`: parent story reference.
- `content`: story text shown in the UI.
- `is_root`: marks the single entry node.
- `is_ending`: marks leaf nodes.
- `is_winning_ending`: distinguishes successful endings from losing endings.
- `options`: JSON array of `{ text, node_id }`.

This is the key structural choice in the repo:

- node relationships are not stored with a `parent_id`,
- instead, forward links are stored inside each node's `options` JSON.

That makes traversal easy for the frontend because every rendered node already contains the button labels and target node IDs it needs.

## 6. How the Tree Is Persisted

After Gemini returns the nested tree, `_process_story_node()` recursively walks it.

For each node:

1. create a `StoryNode` row,
2. flush to get its database `id`,
3. recurse into each option's `nextNode`,
4. collect child node IDs,
5. save `options=[{text, node_id}, ...]` on the parent node.

That means the final DB shape is flat storage with logical tree links embedded as JSON references.

## 7. Read Flow After Generation

### Polling job status

The frontend calls:

- `GET /api/jobs/{job_id}`

This endpoint only returns the job row. It does not generate or assemble anything.

### Fetching the finished story

Once the job says `completed` and exposes `story_id`, the frontend calls:

- `GET /api/stories/{story_id}/complete`

This endpoint:

1. loads the `Story`,
2. loads all `StoryNode` rows for that story,
3. builds an in-memory `node_dict`,
4. finds the root node,
5. returns:
   - story metadata,
   - `root_node`,
   - `all_nodes`.

This response is optimized for the current React game UI, which needs instant client-side traversal after the initial fetch.

## 8. Frontend-to-Backend Contract

The backend currently supports this frontend flow:

1. user submits a theme,
2. frontend receives `{ job_id, status }`,
3. frontend polls `/jobs/{job_id}`,
4. when `story_id` appears, frontend navigates to `/story/{story_id}`,
5. frontend fetches `/stories/{story_id}/complete`,
6. gameplay becomes purely client-side using `all_nodes`.

This is a strong separation:

- generation is backend-side,
- story traversal is frontend-side after load.

## 9. Current Architectural Strengths

- Simple mental model: one request creates one job and one final story.
- Good UX: long generation does not block the browser.
- Clean frontend contract: polling plus one final story fetch.
- Durable tracking: jobs persist status and failure details.
- Portable persistence model: stories survive page refreshes and app restarts.

## 10. Current Constraints and Risks

### 1. Background task execution is process-local

FastAPI background tasks run in the app process. If the server restarts mid-generation:

- the job row survives,
- the in-memory task does not.

That can leave jobs stuck in `processing`.

### 2. Story generation is single-shot

Gemini must return the entire tree in one response. If the response is malformed or truncated, the whole generation fails.

### 3. No ownership enforcement on reads

The session ID is stored, but `GET /jobs/{job_id}` and `GET /stories/{story_id}/complete` do not currently verify that the requester owns that resource.

### 4. `options` uses JSON instead of relational edges

This keeps reads simple, but makes graph analytics, edge-level querying, and DB-enforced referential integrity harder.

### 5. No observability layer yet

There is no explicit logging, token accounting, retry policy, or generation metrics pipeline.

## 11. Recommended Next Structural Upgrades

### Short-term

- Add provider-level error logging around Gemini responses.
- Validate that returned trees have exactly one root and at least one winning ending before commit.
- Enforce session ownership checks on job/story fetch endpoints.
- Add retry handling for transient model failures.

### Mid-term

- Move job execution to a real queue worker model such as Celery, RQ, or Dramatiq.
- Add `parent_node_id` or a separate edges table if story analytics become important.
- Store raw model response JSON for debugging and replay.
- Add story metadata such as depth, node count, ending count, and winning-path count.

### Frontend-facing backend enhancements

- Add `GET /api/stories` for session-scoped story history.
- Add pagination for past stories.
- Add resumable sessions if you later want save-state gameplay instead of full client-only traversal.

## 12. Recommended Future Landing-Page Alignment

Since the frontend landing page is intentionally basic right now, the backend is already stable enough to support a richer product surface later:

- generation history,
- recent story cards,
- theme suggestions,
- loading progress states,
- saved adventures,
- replay and share links.

The current backend contract is a good base for that, because jobs and stories are already separated cleanly.
