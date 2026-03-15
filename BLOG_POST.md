# Breaking the Text Box: How I Built Vibe Story for the Gemini Live Agent Challenge

*A dev-to-dev deep dive into real-time multimodal AI, agent orchestration, and the new frontier of conversational content creation.*

---

## The Inspiration

It started with a bedtime story.

I was watching a parent try to tell their kid a story using one of those AI image generators — type a prompt, wait, get an image, back to the keyboard, type again. The magic was completely absent. The child was bored. The parent was frustrated. And I realized: **we've been building the wrong thing**.

Storytelling isn't a prompt. It's a conversation. It's *"what if the dragon was blue?"* and *"can the princess have a robot friend?"* fired off in real-time, interrupting each other, building on each other. It's dynamic, alive, and deeply human.

But every AI creative tool I knew treated it like a vending machine — insert prompt, receive output, repeat.

That's when the idea for **Vibe Story Lab** crystallized. What if the AI wasn't a tool you operated, but a *creative partner you talked to?* What if you could co-author an animated cinematic story — with original characters, rendered scenes, and a narrated soundtrack — just by having a conversation?

The **Gemini Live Agent Challenge** gave me the perfect excuse to build it.

---

## The Architecture of a Storyteller

> *"The best systems are the ones that disappear. The user shouldn't think about the pipeline — they should think about their story."*

Building Vibe Story Lab meant solving a deceptively hard problem: how do you turn a free-flowing, multi-turn voice conversation into a production-quality animated video, in near-real-time, without the user ever touching a keyboard?

The answer: **a multi-agent pipeline orchestrated by the Agent Development Kit (ADK)**, backed by a distributed task queue, and powered by Google's most capable generative models.

Here's how the pieces fit together.

---

### The Orchestrator: ADK as the Brain

At the heart of Vibe Story Lab is the **Agent Development Kit (ADK)** — Google's framework for building composable, production-grade AI agents. ADK gave us something invaluable: **the ReAct (Reason and Act) loop**, a cognitive architecture where the agent doesn't just execute instructions linearly — it reasons about the current state of the world, decides what action to take next, acts, observes the result, and reasons again.

In practice, this means the pipeline isn't a rigid script. It's an adaptive system. If Veo 3.1 returns a video clip that's unexpectedly short, the orchestrator *notices*, *reasons* about the gap, and *decides* to retry with adjusted parameters — without manual intervention.

The pipeline is structured in five phases, each handled by a specialized sub-agent:

```
Phase 1 (parallel)
  ├── Narration Agent × N   → MP3 audio per scene
  └── Character Agent × M   → PNG character reference sheets

Phase 2
  └── Scene Prompt Agent    → Detailed visual plan (image + video prompts)

Phase 3 (concurrent)
  └── Scene Image Agent × K → PNG scene illustrations

Phase 4 (concurrent, gated on Phase 3)
  └── Scene Video Agent × K → MP4 cinematic clips per scene

Phase 5
  └── Compile Agent         → Final MP4 (FFmpeg assembly)
```

Each agent is a composable unit with a single responsibility. The orchestrator wires them together, manages dependencies (Phase 4 can't start until Phase 3 images are ready), and streams progress events back to the browser via WebSocket throughout.

> **[Insert architecture diagram here — `assets/agent_flow.png`]**

---

### The Visionary Stack

Here's where the engineering gets genuinely exciting. Every layer of the generative pipeline was chosen for a specific reason:

**🧠 Gemini Live (`gemini-live-2.5-flash-native-audio`) — The Conversation Layer**

This is the engine that makes everything feel alive. Gemini Live enables **full-duplex, real-time audio** — meaning the AI and user can speak simultaneously. No push-to-talk. No turn-taking. No awkward "please wait" spinners. You can interrupt the AI mid-sentence to change direction, and it adapts instantly. The conversation transcript — the raw material of the story — is accumulated in real-time and saved to `StoryState`.

**📝 Gemini 3.1 Pro — The Story Intelligence**

Once the conversation ends, `gemini-3.1-pro-preview` takes over as the *narrative architect*. It decomposes the free-form transcript into a structured story breakdown: scenes, characters, props, emotional arcs, and visual cues. It also handles the **Edit Agent** role — when you describe changes via voice, Gemini Pro analyzes the transcript, builds an `EditPlan`, and identifies the precise set of "dirty nodes" in the dependency graph that need regeneration. This is surgical editing at the model level.

**🖼️ Gemini Flash Image (`gemini-2.5-flash-image-preview`) + Nano Banana 2 — Scene Asset Generation**

Scene assets are where the story becomes visual. Gemini Flash Image handles **character reference sheets** (multi-angle, consistent across all scenes) and **scene illustrations** rendered at 2K in 9:16 aspect ratio. Nano Banana 2 powers the scene asset pipeline's most demanding generation passes — where image fidelity and character consistency under tight latency constraints are non-negotiable. The visual plan produced by the Scene Prompt Agent provides character-aware context to each generation call, ensuring the dragon in scene 1 looks exactly like the dragon in scene 4.

**🎬 Veo 3.1 (`veo-3.1-generate-001`) — Cinematic Video**

Veo 3.1 is the showstopper. It takes each scene image as a reference frame and generates **cinematic MP4 clips** — complete with motion, camera movement, and atmospheric depth. Running on Vertex AI, Veo jobs are I/O-bound rather than CPU-bound, so we can fire multiple generation requests concurrently and let GCP handle the scale. Scene clips are stored in a dedicated **Google Cloud Storage bucket** for Veo I/O, then pulled into the final compilation step.

**🗣️ ElevenLabs (`eleven_multilingual_v2`) — Narration**

Every scene gets professional narration synthesized in parallel with character sheet generation (Phase 1). ElevenLabs' multilingual model means Vibe Story Lab can tell stories in virtually any language without rebuilding the pipeline.

**🎵 Lyria 3 — The Dynamic Score** *(Coming Soon)*

One of the most exciting pieces on the roadmap is integration with **Lyria 3** for AI-composed background music. The vision: a generative score that dynamically matches each scene's emotional tone — swelling orchestral strings for the climactic battle, gentle piano for the quiet resolution. The compilation agent's architecture already accounts for a music stem input track; Lyria 3 will slot in as Phase 1.5.

---

### The Full Tech Stack at a Glance

| Layer | Technology | Role |
|:------|:-----------|:-----|
| **🎙️ Conversation** | Gemini Live (`gemini-live-2.5-flash-native-audio`) | Real-time, interruptible voice dialogue |
| **📝 Story Intelligence** | Gemini 3.1 Pro | Story breakdown, scene planning, edit analysis |
| **🖼️ Image Generation** | Gemini Flash Image + Nano Banana 2 | Character sheets & scene illustrations |
| **🎬 Video Generation** | Veo 3.1 | Cinematic scene clips from reference images |
| **🗣️ Narration** | ElevenLabs | Professional multilingual TTS |
| **🤖 Agent Framework** | Agent Development Kit (ADK) | Orchestration, ReAct loop, sub-agent composition |
| **☁️ Infrastructure** | Vertex AI on GCP | Model serving, auth, and orchestration |
| **📬 Task Queue** | Celery + RabbitMQ | Distributed async pipeline execution |
| **📦 Storage** | GCS + MinIO | Veo I/O + local artifact persistence |
| **🗄️ Database** | Firebase | Session, story, and analytics persistence |
| **⚡ Backend** | FastAPI + Uvicorn | Async REST + WebSocket server |
| **🖥️ Frontend** | Vite + TypeScript | Zero-framework SPA |
| **🐳 Deployment** | Docker Compose on GCE | Containerized production stack |
| **🔄 CI/CD** | GitHub Actions | Auto-deploy on merge to `main` |

---

### Production Grade: The "Vibe Coding" Workflow on GCP

Let me be direct about something: this project was built **fast**. The ADK's agent abstractions meant I could focus on the *experience* rather than boilerplate integration code. Each agent — conversation, story, character, scene image, scene video, narration, edit — is an independent, composable unit. The pipeline orchestrator wires them together. The result is a codebase that reads like a creative brief, not an infrastructure manual.

But "vibe coding" doesn't mean "cowboy coding." Vibe Story Lab is battle-hardened for production:

**Celery + RabbitMQ for Distributed Pipelines**

Story generation is compute-heavy and long-running — a single full pipeline can take several minutes, spanning five phases and multiple AI models. Without a task queue, the FastAPI server would be blocked and unable to serve concurrent users.

With Celery and RabbitMQ, the API server **publishes a task and returns immediately**. Workers pick up jobs independently. This means:

- **Multiple stories generate simultaneously** — each worker operates in isolation
- **Horizontal scaling** — spin up more worker containers as concurrent demand grows
- **Failure isolation** — a crashed pipeline doesn't take down the API or other users' jobs
- **Built-in retry logic** — Celery's retry mechanism stacks on top of per-agent exponential backoff

```python
# The API server never blocks — it publishes and returns
@app.post("/api/story/generate")
async def generate_story(request: StoryRequest):
    task = generate_story_task.delay(
        transcript=request.transcript,
        session_id=request.session_id
    )
    return {"task_id": task.id, "session_id": request.session_id}

# The Celery worker handles the full pipeline asynchronously
@celery_app.task(bind=True, max_retries=3)
def generate_story_task(self, transcript: str, session_id: str):
    orchestrator = PipelineOrchestrator(session_id)
    orchestrator.run(transcript)
```

**[Insert system orchestration diagram here — `assets/fe_be_orchestration.png`]**

**Vertex AI for Model Serving**

All Gemini and Veo calls run through **Vertex AI** — which gives us managed authentication via service accounts, request routing, quota management, and audit logging. The `google-genai` SDK with `GOOGLE_GENAI_USE_VERTEXAI=true` means switching between development and production is a single environment variable.

**GitHub Actions CI/CD**

Every merge to `main` is a production deploy. A self-hosted GitHub Actions runner on the GCE instance pulls the latest code, rebuilds containers, and restarts services — zero downtime, zero manual SSH.

```
Developer → Pull Request → Merge to main → GitHub Actions
                                                │
                                      docker compose down
                                      docker compose build
                                      docker compose up -d
                                                │
                                          ✅ Live
```

---

### The Ubuntu Edge: Dev Environment & Cloudflare Tunnels

The entire project was developed on **Ubuntu 22.04** — and if you're building AI agent systems on Linux, you already know the advantages: native Docker performance, clean Python environment management with `uv`, and no WSL2 overhead eating into your feedback loops.

For local agent testing against the live Gemini Live API, the challenge is obvious: the browser needs to establish a WebSocket connection to your local FastAPI server, but Gemini Live's bidirectional streaming requires a stable, publicly addressable endpoint.

The solution: **Cloudflare Tunnels**.

```bash
# Expose local backend to the internet for live testing
cloudflared tunnel --url http://localhost:8000
```

This instantly creates a public `*.trycloudflare.com` HTTPS endpoint tunneled to your local server. No port forwarding, no firewall rules, no ngrok rate limits. The browser connects to the Cloudflare URL, the WebSocket upgrades cleanly, and you're testing live voice conversation against your local agent in under 30 seconds.

For a project where the core interaction is full-duplex audio streaming, having a frictionless tunnel to the live API during development was genuinely a game-changer.

---

## Challenges Overcome: The Latency Battle

Building a real-time multimodal generation pipeline is an exercise in confronting latency at every layer. Here are the three hardest problems I hit, and how we solved them.

### 1. The First-Byte Problem

Users expect *something* to happen the moment the conversation ends. But the first pipeline phase — story breakdown by Gemini Pro — takes 5–15 seconds. Show nothing and users assume the app is broken.

**Solution: WebSocket progress streaming.** Every meaningful state transition in the pipeline emits a progress event directly to the browser. Users see:

```
✍️  Writing your story...
🎨  Designing your characters...
🖼️  Painting your world...
🎬  Bringing scenes to life...
🎬  Applying final touches...
```

The perceived wait time collapses. Users are watching *their* story being built in real-time.

**[Insert processing page screenshot here — `assets/processing_page.png`]**

### 2. Veo's Async Nature

Veo 3.1 doesn't return video synchronously — it's a long-running operation that can take 60–120 seconds per clip. Naively awaiting each clip sequentially would make the total video generation time linear in the number of scenes.

**Solution: Concurrent Veo job dispatch.** Phase 4 fires all `scene_video_agent` calls simultaneously, then awaits all futures. The wall-clock time for video generation is bounded by the *slowest single clip*, not the *sum of all clips*. For a 5-scene story, this is a 5x speedup.

```python
# Fire all video generation jobs concurrently
video_futures = [
    asyncio.create_task(
        scene_video_agent.generate(scene, reference_image)
    )
    for scene in story.scenes
]
video_clips = await asyncio.gather(*video_futures)
```

### 3. Character Consistency Across Scenes

The most user-visible quality problem in AI image generation is **character drift** — the hero looks slightly different in each scene because each image prompt is generated independently.

**Solution: Character reference sheets as context injection.** The Character Agent (Phase 1) generates a detailed multi-angle reference sheet for every named character. The Scene Prompt Agent then embeds a base64-encoded reference image directly into every subsequent scene generation call. Gemini Flash Image treats the reference as a visual anchor — the character's face, costume, and proportions remain consistent across all 5, 10, or 20 scenes.

---

## The Voice-Driven Edit Loop: The Feature That Changes Everything

Most AI video tools give you one shot. Generate, watch, start over if you don't like it.

Vibe Story Lab gives you a **conversation**. After watching your generated story, you tap "Edit Story" and start another Gemini Live session:

> *"Make the dragon bigger in scene 2."*
> *"Change the boy's name to Leo."*
> *"The castle should look darker, more ominous."*

The **Edit Agent** (Gemini Pro) analyzes this transcript and produces a structured `EditPlan` — a diff against your current story state. It then propagates "dirtiness" through a **dependency graph** of all generated artifacts:

| You Say... | What Gets Regenerated |
|:-----------|:----------------------|
| *"Make the dragon bigger in scene 2"* | Scene 2 image → Scene 2 video → Final video |
| *"Change the boy's name to Leo"* | Story text → All narration → Final video |
| *"The castle should be darker"* | Visual prompt → Scene image → Scene video → Final video |
| *"Add a new character — a robot"* | Character sheet → **All** scene images/videos featuring them → Final video |

If you change one scene, only that scene rerenders. If you change a character's name, only the narration updates. The pipeline is smart enough to **never redo work that isn't affected by your change**.

```
User: "Make the dragon bigger in scene 2"
         │
         ▼
   Edit Agent (Gemini Pro)
   Produces EditPlan:
   {
     "dirty_nodes": ["scene_2_image", "scene_2_video", "final_video"],
     "updated_scene": { "id": 2, "visual_prompt": "...enormous dragon..." }
   }
         │
         ▼
   Dependency Graph Propagation
   Only scene_2_image, scene_2_video, final_video marked dirty
         │
         ▼
   Selective Pipeline Re-run
   Phase 3 (scene 2 only) → Phase 4 (scene 2 only) → Phase 5
```

This is the feature that makes Vibe Story Lab feel less like a generator and more like a creative collaborator.

---

## What's Next for Vibe Story

The current build is a proof of concept for a much larger idea: **conversational content creation**. The roadmap is genuinely exciting:

- **🎵 Lyria 3 Dynamic Scores** — AI-composed background music that matches each scene's emotional tone, generated in parallel and mixed into the final compile step.

- **🎓 Education Applications** — A teacher describes the American Revolution; students watch a personalized animated documentary. Voice-driven story generation for classroom content in minutes, not hours.

- **🎮 Procedural Game Narratives** — The same pipeline that generates stories could power game worlds where every player's journey is shaped entirely by their voice — no two playthroughs the same.

- **♿ Accessibility First** — Voice-first interfaces remove barriers for creators who can't type, draw, or use traditional creative tools. The goal: anyone with a voice can produce studio-quality animated content.

- **🌍 Multilingual Co-creation** — Gemini's multilingual capabilities and ElevenLabs' voice models already support this. The next step is a full localization layer where stories are co-created and rendered in any language, preserving cultural nuance.

- **📺 Cloud Run Migration** — Moving from Compute Engine to **Cloud Run** for fully serverless, per-request scaling. The current Docker Compose stack is production-solid, but Cloud Run will give us true zero-to-scale elasticity without managing instances.

The long-term vision: a world where the barrier between "I have an idea" and "I have a video" is a single conversation.

---

## Try It Yourself

The live demo is running right now on Google Cloud:

**🌐 [http://34.171.54.149:5173/](http://34.171.54.149:5173/)**

Open it, click "Create Story," allow microphone access, and start talking. Tell it about a dragon who's afraid of fire, or a robot who wants to become a chef, or whatever world is living in your head right now. The pipeline will do the rest.

The full source code is open on GitHub:

**📦 [github.com/akalabri/storyteller](https://github.com/akalabri/storyteller)**

Clone it, run `docker compose up --build`, and you'll have the entire stack — FastAPI backend, Celery workers, RabbitMQ broker, MinIO storage, and Vite frontend — running locally in a single command.

---

## Join the Challenge

This project was built for the **Gemini Live Agent Challenge** — a competition that, in my view, is one of the most interesting developer challenges running right now. The premise is simple: build a real agent using the Gemini Live API. But the possibilities are genuinely boundless.

If you're a developer and you haven't explored the Gemini Live API yet, I'd strongly encourage you to start today. Full-duplex audio with a frontier model, accessed via a clean SDK, running on Vertex AI — this is the infrastructure stack that makes conversational agents actually viable in production. The days of janky voice bots are over.

The future of agents isn't text boxes. It's conversations. And the tools to build them are already here.

---

*Built with ❤️ on Ubuntu 22.04, powered by Google Cloud, orchestrated with ADK.*

*Follow for more posts on agent development, generative media, and production AI systems.*

---

**Tags:** `#AI` `#MachineLearning` `#GeminiAPI` `#GenerativeAI` `#AgentDevelopment` `#GoogleCloud` `#VertexAI` `#WebDev` `#Python` `#FastAPI`
