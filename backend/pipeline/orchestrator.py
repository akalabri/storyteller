"""
Main async pipeline orchestrator for the storyteller backend.

Full pipeline
─────────────
  conversation transcript
      │
  [story_agent]  → StoryBreakdown
      │
  Phase 1 (parallel)
  ├── [narration_agent × N scenes]  sequential — rate limit
  └── [character_agent × M chars]   concurrent
      │ (both complete)
  [scene_prompt_agent] → StoryVisualPlan
      │
  Phase 3 (concurrent)
  [scene_image_agent × sub-scenes]  — asyncio.gather
      │  (each image unlocks its video via asyncio.Event)
  Phase 4 (concurrent, gated)
  [scene_video_agent × sub-scenes]  — asyncio.gather + per-subscene Event
      │
  [compile_agent] → final video

Edit re-run
─────────────
  Given a set of dirty_keys (from edit_agent.plan_edit), only the affected
  pipeline nodes are re-run in dependency order, then the video is recompiled.

Progress
─────────
  Every completed step emits a ProgressEvent via an asyncio.Queue that the
  FastAPI WebSocket endpoint drains and forwards to the browser.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

from backend.agents.character_agent import generate_character_image
from backend.agents.compile_agent import compile_video
from backend.agents.narration_agent import generate_narration
from backend.agents.scene_image_agent import (
    ContentViolationError,
    generate_scene_image,
)
from backend.agents.scene_video_agent import VideoGenerationError, generate_scene_video
from backend.agents.scene_prompt_agent import generate_scene_prompts
from backend.agents.story_agent import generate_story_breakdown
from backend.config import DEV_MODE, DEV_SESSION_ID, DEV_STEPS, FAL_CONCURRENCY, SEQUENTIAL_GENERATION, session_dir
from backend.pipeline.state import (
    PipelineStatus,
    StepStatus,
    StoryState,
)
from backend.db.database import get_db
from backend.db import crud as db_crud
from backend.utils.file_io import safe_filename
from backend.utils.minio_client import upload_session_artifact, upload_session_directory

logger = logging.getLogger(__name__)


class PartialVideoFailure(Exception):
    """Raised when some (but not all) sub-scene videos failed to generate."""

    def __init__(self, failed_keys: list[str]) -> None:
        self.failed_keys = failed_keys
        super().__init__(
            f"Video generation failed for {len(failed_keys)} sub-scene(s): "
            + ", ".join(failed_keys)
        )


def _db(func) -> None:
    """Best-effort DB call — never crashes the pipeline."""
    try:
        db = get_db()
        func(db)
    except Exception as exc:
        logger.warning("DB persist failed: %s", exc)


# ---------------------------------------------------------------------------
# Progress event
# ---------------------------------------------------------------------------

@dataclass
class ProgressEvent:
    step: str
    status: str          # "running" | "done" | "failed" | "skipped"
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "message": self.message,
            "data": self.data,
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class StoryOrchestrator:
    """
    Runs the full (or partial) story generation pipeline for one session.

    Parameters
    ----------
    session_id:
        Unique session identifier.  Output files go to ``sessions/{session_id}/``.
    progress_queue:
        ``asyncio.Queue`` that receives ``ProgressEvent`` objects.  The FastAPI
        WebSocket handler drains this and forwards events to the browser.
    """

    def __init__(
        self,
        session_id: str,
        progress_queue: asyncio.Queue | None = None,
    ) -> None:
        self.session_id = session_id
        self.out_dir = session_dir(session_id)
        self.state_path = self.out_dir / "story_state.json"
        self.progress_queue: asyncio.Queue = progress_queue or asyncio.Queue()

        # Persistent state (load from disk if exists)
        if self.state_path.exists():
            self.state = StoryState.load(self.state_path)
        else:
            self.state = StoryState(session_id=session_id)

        # Per-subscene Events: video waits until image is ready
        self._image_events: dict[str, asyncio.Event] = {}

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _emit(self, event: ProgressEvent) -> None:
        self.progress_queue.put_nowait(event)
        self.state.update_step(
            event.step,
            StepStatus(event.status) if event.status in StepStatus._value2member_map_ else StepStatus.RUNNING,
            event.message,
        )
        # Record step in Firestore
        _db(lambda db: db_crud.record_step(db, self.session_id, event.step, event.status, event.message))

    def _save(self) -> None:
        self.state.save(self.state_path)
        # Update session status in Firestore
        _db(lambda db: db_crud.update_session_status(db, self.session_id, self.state.status.value))

    async def _upload_to_minio(self, local_path: str, relative_path: str) -> None:
        """Best-effort upload of a single file to MinIO."""
        print(f"[Orchestrator] _upload_to_minio called: local={local_path}, rel={relative_path}")
        try:
            await upload_session_artifact(self.session_id, local_path, relative_path)
            print(f"[Orchestrator] _upload_to_minio OK: {relative_path}")
        except Exception as exc:
            print(f"[Orchestrator] _upload_to_minio FAILED: {relative_path} — {exc}")
            import traceback; traceback.print_exc()

    async def _upload_dir_to_minio(self, local_dir: Path, prefix: str) -> None:
        """Best-effort upload of all files in a directory to MinIO."""
        print(f"[Orchestrator] _upload_dir_to_minio called: dir={local_dir}, prefix={prefix}")
        try:
            await upload_session_directory(self.session_id, str(local_dir), prefix)
            print(f"[Orchestrator] _upload_dir_to_minio OK: {prefix}")
        except Exception as exc:
            print(f"[Orchestrator] _upload_dir_to_minio FAILED: {prefix} — {exc}")
            import traceback; traceback.print_exc()

    def _char_dir(self) -> Path:
        return self.out_dir / "characters"

    def _narration_dir(self) -> Path:
        return self.out_dir / "narration"

    def _scenes_dir(self) -> Path:
        return self.out_dir / "scenes"

    def _videos_dir(self) -> Path:
        return self.out_dir / "videos"

    def _final_dir(self) -> Path:
        return self.out_dir / "final"

    def _character_image_paths(self) -> list[str]:
        return [
            p for p in self.state.character_image_paths.values()
            if Path(p).exists()
        ]

    def _subscene_event(self, key: str) -> asyncio.Event:
        if key not in self._image_events:
            self._image_events[key] = asyncio.Event()
        return self._image_events[key]

    # -----------------------------------------------------------------------
    # Dev-skip: bootstrap current session from cached dev_session artifacts
    # -----------------------------------------------------------------------

    # Pipeline step order — used to decide if a missing artifact is a
    # prerequisite (before what's running) or downstream (after).
    _STEP_ORDER = [
        "story_breakdown",
        "narration",
        "character_images",
        "scene_prompts",
        "scene_images",
        "scene_videos",
        "compile",
    ]

    def _apply_dev_mode(self) -> None:
        """
        When DEV_MODE=1, load the dev session's StoryState and pre-populate
        every step that is NOT listed in DEV_STEPS.

        Steps in DEV_STEPS will run normally.  For every other step:
        - If it comes BEFORE the first step in DEV_STEPS (a prerequisite) and
          its artifacts are missing from the dev session → raise immediately.
        - If it comes AFTER the last step in DEV_STEPS (downstream / unused
          in this run) and its artifacts are missing → log a warning and skip.

        File paths stored in the dev session are reused as-is (no copying).
        """
        from backend.config import SESSIONS_DIR  # local import to avoid circularity

        dev_state_path = SESSIONS_DIR / DEV_SESSION_ID / "story_state.json"
        if not dev_state_path.exists():
            raise FileNotFoundError(
                f"DEV_MODE is enabled but no dev session found at {dev_state_path}. "
                f"Run the full pipeline once with DEV_MODE=0 and session_id='{DEV_SESSION_ID}' "
                f"to create the cached session."
            )

        dev = StoryState.load(dev_state_path)
        logger.info(
            "DEV_MODE: bootstrapping from dev session '%s'. Running steps: %s",
            DEV_SESSION_ID,
            sorted(DEV_STEPS) if DEV_STEPS else "(none — loading everything)",
        )

        # Determine the index range of steps we're actually running so we
        # know which missing artifacts are blockers vs. irrelevant.
        running_indices = [
            self._STEP_ORDER.index(s)
            for s in DEV_STEPS
            if s in self._STEP_ORDER
        ]
        first_running = min(running_indices) if running_indices else len(self._STEP_ORDER)

        def _need_artifact(step_name: str) -> bool:
            """True if missing artifacts for this step should be a hard error."""
            try:
                idx = self._STEP_ORDER.index(step_name)
            except ValueError:
                return False
            # Only require it if it's a prerequisite (before the first running step)
            return idx < first_running

        # ── conversation transcript (always loaded; not a pipeline step) ──────
        if dev.conversation_transcript and not self.state.conversation_transcript:
            self.state.conversation_transcript = dev.conversation_transcript
            logger.info("DEV_MODE: loaded conversation_transcript from dev session")

        # ── story_breakdown ───────────────────────────────────────────────────
        if "story_breakdown" not in DEV_STEPS:
            if dev.breakdown is None:
                if _need_artifact("story_breakdown"):
                    raise ValueError(
                        "DEV_MODE: 'story_breakdown' is not in DEV_STEPS but the dev session "
                        "has no story breakdown. Add 'story_breakdown' to DEV_STEPS or run "
                        "the full pipeline first to cache it."
                    )
                logger.warning("DEV_MODE: no story breakdown in dev session — skipping (not needed)")
            else:
                self.state.breakdown = dev.breakdown
                logger.info(
                    "DEV_MODE: loaded story breakdown (%d scenes) from dev session",
                    len(dev.breakdown.story),
                )

        # ── narration ─────────────────────────────────────────────────────────
        if "narration" not in DEV_STEPS:
            if not dev.narration_paths:
                if _need_artifact("narration"):
                    raise ValueError(
                        "DEV_MODE: 'narration' is not in DEV_STEPS but the dev session has no "
                        "narration paths. Add 'narration' to DEV_STEPS or run the full pipeline first."
                    )
                logger.warning("DEV_MODE: no narration in dev session — skipping (not needed)")
            else:
                missing = [p for p in dev.narration_paths.values() if not Path(p).exists()]
                if missing and _need_artifact("narration"):
                    raise FileNotFoundError(
                        f"DEV_MODE: narration files missing from dev session: {missing}"
                    )
                for key, path in dev.narration_paths.items():
                    if key not in self.state.narration_paths and Path(path).exists():
                        self.state.narration_paths[key] = path
                logger.info(
                    "DEV_MODE: loaded %d narration path(s) from dev session",
                    len(dev.narration_paths),
                )

        # ── character_images ──────────────────────────────────────────────────
        # Character images are only consumed by scene_images and scene_videos;
        # steps like compile don't need them, so only treat them as a hard
        # prerequisite when those image/video steps are actually running.
        _CHAR_CONSUMERS = {"scene_images", "scene_videos"}
        if "character_images" not in DEV_STEPS:
            chars_needed = bool(DEV_STEPS & _CHAR_CONSUMERS)
            if not dev.character_image_paths:
                if chars_needed:
                    raise ValueError(
                        "DEV_MODE: 'character_images' is not in DEV_STEPS but the dev session "
                        "has no character images. Add 'character_images' to DEV_STEPS or run "
                        "the full pipeline first."
                    )
                logger.warning("DEV_MODE: no character images in dev session — skipping (not needed)")
            else:
                missing = [p for p in dev.character_image_paths.values() if not Path(p).exists()]
                if missing and chars_needed:
                    raise FileNotFoundError(
                        f"DEV_MODE: character image files missing from dev session: {missing}"
                    )
                for slug, path in dev.character_image_paths.items():
                    if slug not in self.state.character_image_paths and Path(path).exists():
                        self.state.character_image_paths[slug] = path
                logger.info(
                    "DEV_MODE: loaded %d character image(s) from dev session",
                    len(dev.character_image_paths),
                )

        # ── scene_prompts ─────────────────────────────────────────────────────
        if "scene_prompts" not in DEV_STEPS:
            if dev.visual_plan is None:
                if _need_artifact("scene_prompts"):
                    raise ValueError(
                        "DEV_MODE: 'scene_prompts' is not in DEV_STEPS but the dev session "
                        "has no visual plan. Add 'scene_prompts' to DEV_STEPS or run the "
                        "full pipeline first."
                    )
                logger.warning("DEV_MODE: no visual plan in dev session — skipping (not needed)")
            else:
                self.state.visual_plan = dev.visual_plan
                logger.info("DEV_MODE: loaded visual plan from dev session")

        # ── scene_images ──────────────────────────────────────────────────────
        if "scene_images" not in DEV_STEPS:
            if not dev.scene_image_paths:
                if _need_artifact("scene_images"):
                    raise ValueError(
                        "DEV_MODE: 'scene_images' is not in DEV_STEPS but the dev session "
                        "has no scene images. Add 'scene_images' to DEV_STEPS or run the "
                        "full pipeline first."
                    )
                logger.warning("DEV_MODE: no scene images in dev session — skipping (not needed)")
            else:
                missing = [p for p in dev.scene_image_paths.values() if not Path(p).exists()]
                if missing and _need_artifact("scene_images"):
                    raise FileNotFoundError(
                        f"DEV_MODE: scene image files missing from dev session: {missing}"
                    )
                for key, path in dev.scene_image_paths.items():
                    if key not in self.state.scene_image_paths and Path(path).exists():
                        self.state.scene_image_paths[key] = path
                logger.info(
                    "DEV_MODE: loaded %d scene image(s) from dev session",
                    len(dev.scene_image_paths),
                )

        # ── scene_videos ──────────────────────────────────────────────────────
        if "scene_videos" not in DEV_STEPS:
            if not dev.scene_video_paths:
                if _need_artifact("scene_videos"):
                    raise ValueError(
                        "DEV_MODE: 'scene_videos' is not in DEV_STEPS but the dev session "
                        "has no scene videos. Add 'scene_videos' to DEV_STEPS or run the "
                        "full pipeline first."
                    )
                logger.warning("DEV_MODE: no scene videos in dev session — skipping (not needed)")
            else:
                missing = [p for p in dev.scene_video_paths.values() if not Path(p).exists()]
                if missing and _need_artifact("scene_videos"):
                    raise FileNotFoundError(
                        f"DEV_MODE: scene video files missing from dev session: {missing}"
                    )
                for key, path in dev.scene_video_paths.items():
                    if key not in self.state.scene_video_paths and Path(path).exists():
                        self.state.scene_video_paths[key] = path
                logger.info(
                    "DEV_MODE: loaded %d scene video(s) from dev session",
                    len(dev.scene_video_paths),
                )

        # ── compile ───────────────────────────────────────────────────────────
        if "compile" not in DEV_STEPS:
            if dev.final_video_path and Path(dev.final_video_path).exists():
                self.state.final_video_path = dev.final_video_path
                logger.info("DEV_MODE: loaded final video path from dev session")

        self._save()

    # -----------------------------------------------------------------------
    # Step: story breakdown
    # -----------------------------------------------------------------------

    async def _run_story_breakdown(self) -> None:
        if self.state.breakdown is not None:
            return
        if not self.state.conversation_transcript:
            raise ValueError("conversation_transcript must be set before running the pipeline")

        self._emit(ProgressEvent("story_breakdown", "running"))
        try:
            breakdown = await generate_story_breakdown(self.state.conversation_transcript)
            self.state.breakdown = breakdown
            self._emit(ProgressEvent(
                "story_breakdown", "done",
                message=f"{len(breakdown.story)} scenes, {len(breakdown.characters_prompts)} characters",
            ))
            # Persist breakdown to Firestore
            _db(lambda db: db_crud.save_story_breakdown(db, self.session_id, breakdown))
        except Exception as exc:
            self.state.add_error(f"story_breakdown: {exc}")
            self._emit(ProgressEvent("story_breakdown", "failed", message=str(exc)))
            raise
        finally:
            self._save()
            await self._upload_to_minio(str(self.state_path), "story_state.json")

    # -----------------------------------------------------------------------
    # Phase 1a: narration (sequential)
    # -----------------------------------------------------------------------

    async def _run_narration_sequential(self, dirty_scenes: set[int] | None = None) -> None:
        """Generate narration for all (or specified) scenes, one at a time."""
        assert self.state.breakdown is not None
        narration_dir = self._narration_dir()

        for i, scene_text in enumerate(self.state.breakdown.story, start=1):
            key = str(i)
            if dirty_scenes is not None and i not in dirty_scenes:
                continue
            # Skip if already done and not dirty
            if dirty_scenes is None and key in self.state.narration_paths:
                continue

            step = f"narration:{i}"
            self._emit(ProgressEvent(step, "running"))
            try:
                await generate_narration(
                    scene_text=scene_text,
                    audio_path=narration_dir / f"scene_{i}.mp3",
                    timestamps_path=narration_dir / f"scene_{i}_timestamps.json",
                )
                self.state.narration_paths[key] = str(narration_dir / f"scene_{i}.mp3")
                self._emit(ProgressEvent(step, "done"))
                # Upload narration files to MinIO
                await self._upload_to_minio(
                    str(narration_dir / f"scene_{i}.mp3"), f"narration/scene_{i}.mp3"
                )
                await self._upload_to_minio(
                    str(narration_dir / f"scene_{i}_timestamps.json"),
                    f"narration/scene_{i}_timestamps.json",
                )
            except Exception as exc:
                self.state.add_error(f"{step}: {exc}")
                self._emit(ProgressEvent(step, "failed", message=str(exc)))
                # Non-fatal — continue with remaining scenes
            finally:
                self._save()

    # -----------------------------------------------------------------------
    # Phase 1b: character images (concurrent)
    # -----------------------------------------------------------------------

    async def _run_character_images(self, dirty_chars: set[str] | None = None) -> None:
        assert self.state.breakdown is not None
        char_dir = self._char_dir()

        async def _gen_one(char):
            slug = safe_filename(char.name)
            if dirty_chars is not None and slug not in dirty_chars:
                return
            if dirty_chars is None and slug in self.state.character_image_paths:
                return
            step = f"character:{slug}"
            self._emit(ProgressEvent(step, "running"))
            try:
                name, path = await generate_character_image(char, char_dir)
                self.state.character_image_paths[slug] = path
                self._emit(ProgressEvent(step, "done", data={"path": path}))
                await self._upload_to_minio(path, f"characters/{Path(path).name}")
            except Exception as exc:
                self.state.add_error(f"{step}: {exc}")
                self._emit(ProgressEvent(step, "failed", message=str(exc)))
            finally:
                self._save()

        if SEQUENTIAL_GENERATION:
            for char in self.state.breakdown.characters_prompts:
                await _gen_one(char)
        else:
            await asyncio.gather(*[_gen_one(c) for c in self.state.breakdown.characters_prompts])

    # -----------------------------------------------------------------------
    # Phase 2: scene prompts
    # -----------------------------------------------------------------------

    async def _run_scene_prompts(self) -> None:
        assert self.state.breakdown is not None
        if self.state.visual_plan is not None:
            return

        self._emit(ProgressEvent("visual_plan", "running"))
        try:
            plan = await generate_scene_prompts(self.state.breakdown)
            self.state.visual_plan = plan
            self._emit(ProgressEvent("visual_plan", "done"))
            # Persist visual plan to Firestore
            _db(lambda db: db_crud.save_visual_plan(db, self.session_id, plan))
        except Exception as exc:
            self.state.add_error(f"visual_plan: {exc}")
            self._emit(ProgressEvent("visual_plan", "failed", message=str(exc)))
            raise
        finally:
            self._save()

    async def _force_regen_scene_prompts(self) -> None:
        """Regenerate scene prompts unconditionally (used during edit)."""
        assert self.state.breakdown is not None
        self.state.visual_plan = None
        await self._run_scene_prompts()

    # -----------------------------------------------------------------------
    # Phase 3: scene images (concurrent, rate-limited)
    # -----------------------------------------------------------------------

    # Max concurrent image-gen requests to avoid Vertex AI 429 rate limits
    _SCENE_IMAGE_CONCURRENCY = 1

    async def _run_scene_images(self, dirty_keys: set[str] | None = None) -> None:
        """
        Generate all sub-scene images concurrently (up to _SCENE_IMAGE_CONCURRENCY
        at a time).

        Failure policy
        ──────────────
        Every sub-scene is attempted regardless of other failures so that we
        collect as many images as possible.  After all tasks complete, if ANY
        image failed to generate this method raises ``RuntimeError`` listing
        every failed sub-scene key.  The caller must not proceed to video
        generation when this raises.
        """
        assert self.state.visual_plan is not None
        scenes_dir = self._scenes_dir()
        char_paths = self._character_image_paths()
        concurrency = 1 if SEQUENTIAL_GENERATION else self._SCENE_IMAGE_CONCURRENCY
        sem = asyncio.Semaphore(concurrency)

        failed_keys: list[str] = []

        async def _gen_one(scene_idx: int, sub_idx: int, image_prompt: str) -> None:
            sub_key = f"scene_{scene_idx}_sub_{sub_idx}"
            event = self._subscene_event(sub_key)

            if dirty_keys is not None and f"scene_image:{sub_key}" not in dirty_keys:
                # Not dirty — signal event immediately so video can proceed
                if sub_key in self.state.scene_image_paths:
                    event.set()
                return

            # Delete the existing file so the agent doesn't skip it
            existing = scenes_dir / f"scene_{scene_idx}_sub_{sub_idx}.png"
            if existing.exists():
                existing.unlink()

            async with sem:
                step = f"scene_image:{sub_key}"
                self._emit(ProgressEvent(step, "running"))
                try:
                    key, path = await generate_scene_image(
                        scene_idx, sub_idx, image_prompt, char_paths, scenes_dir
                    )
                    self.state.scene_image_paths[key] = path
                    self._emit(ProgressEvent(step, "done", data={"path": path}))
                    await self._upload_to_minio(path, f"scenes/{Path(path).name}")
                    event.set()  # unblock corresponding video job

                except ContentViolationError as exc:
                    # Content policy refusal — non-retryable, log clearly
                    failed_keys.append(sub_key)
                    self.state.add_error(f"{step}: content violation — {exc}")
                    self._emit(ProgressEvent(
                        step, "failed",
                        message=f"Content policy violation: {exc}",
                    ))
                    event.set()  # release video waiter so it can skip cleanly

                except Exception as exc:
                    failed_keys.append(sub_key)
                    self.state.add_error(f"{step}: {exc}")
                    self._emit(ProgressEvent(step, "failed", message=str(exc)))
                    event.set()  # release video waiter so it can skip cleanly

                finally:
                    self._save()

        tasks = [
            _gen_one(s.scene_index, sub.index, sub.image_prompt)
            for s in self.state.visual_plan.scenes
            for sub in s.subscenes
        ]
        await asyncio.gather(*tasks)

        if failed_keys:
            msg = (
                f"Scene image generation failed for {len(failed_keys)} sub-scene(s): "
                + ", ".join(failed_keys)
                + ". Continuing with successfully generated images."
            )
            logger.warning(msg)
            self.state.add_error(msg)
            self._save()

    # -----------------------------------------------------------------------
    # Phase 4: scene videos (concurrent, gated on image Events)
    # -----------------------------------------------------------------------

    async def _run_scene_videos(self, dirty_keys: set[str] | None = None) -> None:
        """
        Generate all sub-scene videos concurrently, each gated on its
        corresponding scene image Event.

        Failure policy
        ──────────────
        Every sub-scene is attempted regardless of other failures so that we
        collect as many videos as possible.  Sub-scenes whose images were not
        generated are skipped cleanly.  After all tasks complete, if ANY video
        failed this method raises ``RuntimeError`` listing every failed key.
        The caller must not proceed to compilation when this raises.
        """
        assert self.state.visual_plan is not None
        videos_dir = self._videos_dir()
        char_paths = self._character_image_paths()

        # Limit concurrent FAL requests to avoid hitting FAL's per-minute quota.
        fal_sem = asyncio.Semaphore(1 if SEQUENTIAL_GENERATION else FAL_CONCURRENCY)

        failed_keys: list[str] = []

        async def _gen_one(scene_idx: int, sub_idx: int, video_prompt: str) -> None:
            sub_key = f"scene_{scene_idx}_sub_{sub_idx}"

            if dirty_keys is not None and f"scene_video:{sub_key}" not in dirty_keys:
                return

            # Delete the existing file so the agent doesn't skip it
            existing = videos_dir / f"scene_{scene_idx}_sub_{sub_idx}.mp4"
            if existing.exists():
                existing.unlink()

            # Wait until the corresponding scene image is ready (or failed)
            await self._subscene_event(sub_key).wait()

            scene_img_path = self.state.scene_image_paths.get(sub_key)
            if not scene_img_path or not Path(scene_img_path).exists():
                self._emit(ProgressEvent(
                    f"scene_video:{sub_key}", "skipped",
                    message=(
                        f"Skipped: scene image for '{sub_key}' was not generated "
                        "(see scene_image errors above)."
                    ),
                ))
                return

            step = f"scene_video:{sub_key}"
            self._emit(ProgressEvent(step, "running"))
            try:
                key, path = await generate_scene_video(
                    scene_idx, sub_idx, video_prompt,
                    scene_img_path, char_paths, videos_dir,
                    fal_sem=fal_sem,
                )
                self.state.scene_video_paths[key] = path
                self._emit(ProgressEvent(step, "done", data={"path": path}))
                await self._upload_to_minio(path, f"videos/{Path(path).name}")

            except VideoGenerationError as exc:
                failed_keys.append(sub_key)
                self.state.add_error(f"{step}: {exc}")
                self._emit(ProgressEvent(step, "failed", message=str(exc)))

            except Exception as exc:
                failed_keys.append(sub_key)
                self.state.add_error(f"{step}: {exc}")
                self._emit(ProgressEvent(step, "failed", message=str(exc)))

            finally:
                self._save()

        subscenes = [
            (s.scene_index, sub.index, sub.video_prompt)
            for s in self.state.visual_plan.scenes
            for sub in s.subscenes
        ]
        if SEQUENTIAL_GENERATION:
            for scene_idx, sub_idx, video_prompt in subscenes:
                await _gen_one(scene_idx, sub_idx, video_prompt)
        else:
            await asyncio.gather(*[
                _gen_one(scene_idx, sub_idx, video_prompt)
                for scene_idx, sub_idx, video_prompt in subscenes
            ])

        if failed_keys:
            self.state.failed_video_keys = list(failed_keys)
            self._save()
            raise PartialVideoFailure(failed_keys)

    # -----------------------------------------------------------------------
    # Compile
    # -----------------------------------------------------------------------

    async def _run_compile(self) -> None:
        assert self.state.breakdown is not None
        assert self.state.visual_plan is not None

        self._emit(ProgressEvent("compile", "running"))
        version = len(self.state.edit_history) + 1
        filename = f"story_v{version}.mp4"
        output_path = self._final_dir() / filename
        try:
            path = await compile_video(
                breakdown=self.state.breakdown,
                visual_plan=self.state.visual_plan,
                narration_dir=self._narration_dir(),
                videos_dir=self._videos_dir(),
                output_path=output_path,
            )
            self.state.final_video_path = path
            self._emit(ProgressEvent("compile", "done", data={"path": path}))
            await self._upload_to_minio(path, f"final/{filename}")
        except Exception as exc:
            self.state.add_error(f"compile: {exc}")
            self._emit(ProgressEvent("compile", "failed", message=str(exc)))
            raise
        finally:
            self._save()

    # -----------------------------------------------------------------------
    # Public: full pipeline run
    # -----------------------------------------------------------------------

    async def run_full_pipeline(self, conversation_transcript: str) -> StoryState:
        """
        Execute the complete pipeline end-to-end.

        Steps
        -----
        1.  story_breakdown
        2a. narration (sequential) ┐ parallel
        2b. character images        ┘
        3.  scene_prompts
        4.  scene_images (concurrent)  ┐ images gate videos
        5.  scene_videos (concurrent)  ┘
        6.  compile
        """
        self.state.status = PipelineStatus.RUNNING
        self.state.conversation_transcript = conversation_transcript
        self._save()

        # Save conversation transcript to Firestore
        _db(lambda db: db_crud.save_conversation(db, self.session_id, conversation_transcript))

        try:
            # Bootstrap from cached dev session when DEV_MODE is enabled.
            # This must run before any step so the "already done" guards fire.
            if DEV_MODE:
                self._apply_dev_mode()

            def _should_run(step: str) -> bool:
                """In DEV_MODE only run steps listed in DEV_STEPS; otherwise run all."""
                return (not DEV_MODE) or (step in DEV_STEPS)

            # Step 1
            if _should_run("story_breakdown"):
                await self._run_story_breakdown()

            # Step 2 — parallel (or sequential when rate-limit mode is on)
            run_narration = _should_run("narration")
            run_chars = _should_run("character_images")
            if run_narration or run_chars:
                if SEQUENTIAL_GENERATION:
                    if run_narration:
                        await self._run_narration_sequential()
                    if run_chars:
                        await self._run_character_images()
                else:
                    tasks = []
                    if run_narration:
                        tasks.append(self._run_narration_sequential())
                    if run_chars:
                        tasks.append(self._run_character_images())
                    await asyncio.gather(*tasks)

            # Step 3
            if _should_run("scene_prompts"):
                await self._run_scene_prompts()

            # Steps 4 + 5 — images gate videos via Events.
            run_images = _should_run("scene_images")
            run_videos = _should_run("scene_videos")
            if run_images or run_videos:
                # When skipping image generation but running videos, the per-subscene
                # Events that gate video jobs are never set by _run_scene_images.
                # Pre-set them here for any images already present in state so video
                # tasks don't block forever.
                if not run_images and run_videos and self.state.visual_plan:
                    for s in self.state.visual_plan.scenes:
                        for sub in s.subscenes:
                            key = f"scene_{s.scene_index}_sub_{sub.index}"
                            if key in self.state.scene_image_paths:
                                self._subscene_event(key).set()

                if SEQUENTIAL_GENERATION:
                    if run_images:
                        await self._run_scene_images()
                    if run_videos:
                        await self._run_scene_videos()
                else:
                    await asyncio.gather(
                        self._run_scene_images() if run_images else asyncio.sleep(0),
                        self._run_scene_videos() if run_videos else asyncio.sleep(0),
                    )

            # Step 6
            if _should_run("compile"):
                await self._run_compile()

            self.state.status = PipelineStatus.DONE

        except PartialVideoFailure as exc:
            logger.warning("Pipeline paused — partial video failure: %s", exc)
            self.state.status = PipelineStatus.PARTIAL_FAILURE
            self.state.add_error(str(exc))
            _db(lambda db: db_crud.record_error(db, self.session_id, str(exc), step="scene_videos"))

        except Exception as exc:
            logger.exception("Pipeline failed: %s", exc)
            self.state.status = PipelineStatus.ERROR
            self.state.add_error(str(exc))
            _db(lambda db: db_crud.record_error(db, self.session_id, str(exc), step="pipeline"))

        finally:
            self._save()
            await self._upload_to_minio(str(self.state_path), "story_state.json")
            self._emit(ProgressEvent(
                "pipeline",
                self.state.status.value,
                message=f"Pipeline {self.state.status.value}",
            ))

        return self.state

    # -----------------------------------------------------------------------
    # Public: selective re-run after edit
    # -----------------------------------------------------------------------

    async def run_selective(self, dirty_keys: set[str]) -> StoryState:
        """
        Re-run only the pipeline nodes present in ``dirty_keys``.

        Called by the FastAPI edit endpoint after edit_agent.plan_edit() has
        already updated self.state in place.

        dirty_keys format (from edit_agent.propagate_dirty_nodes):
            "narration:{scene_idx}"
            "character:{slug}"
            "visual_plan"
            "scene_image:{scene_i_sub_j}"
            "scene_video:{scene_i_sub_j}"
            "final_video"
        """
        self.state.status = PipelineStatus.RUNNING
        self._save()

        # Reset image events so videos don't skip
        self._image_events = {}

        # Pre-populate events for unchanged images so their videos aren't blocked
        if self.state.visual_plan:
            for s in self.state.visual_plan.scenes:
                for sub in s.subscenes:
                    key = f"scene_{s.scene_index}_sub_{sub.index}"
                    if f"scene_image:{key}" not in dirty_keys:
                        # Image not being regenerated — signal event immediately
                        self._subscene_event(key).set()

        try:
            # Visual plan needs full regen if dirty
            if "visual_plan" in dirty_keys:
                await self._force_regen_scene_prompts()

            # Narration — sequential, only dirty scenes
            dirty_narration_scenes = {
                int(k.split(":")[1])
                for k in dirty_keys
                if k.startswith("narration:")
            }
            if dirty_narration_scenes:
                await self._run_narration_sequential(dirty_scenes=dirty_narration_scenes)

            # Character images — concurrent, only dirty slugs
            dirty_char_slugs = {
                k.split(":")[1] for k in dirty_keys if k.startswith("character:")
            }
            if dirty_char_slugs:
                await self._run_character_images(dirty_chars=dirty_char_slugs)

            # Scene images + videos
            dirty_image_keys = {k for k in dirty_keys if k.startswith("scene_image:")}
            dirty_video_keys = {k for k in dirty_keys if k.startswith("scene_video:")}

            if dirty_image_keys or dirty_video_keys:
                if SEQUENTIAL_GENERATION:
                    await self._run_scene_images(dirty_keys=dirty_keys)
                    await self._run_scene_videos(dirty_keys=dirty_keys)
                else:
                    await asyncio.gather(
                        self._run_scene_images(dirty_keys=dirty_keys),
                        self._run_scene_videos(dirty_keys=dirty_keys),
                    )

            # Compile
            if "final_video" in dirty_keys:
                await self._run_compile()

            self.state.status = PipelineStatus.DONE

        except PartialVideoFailure as exc:
            logger.warning("Selective pipeline paused — partial video failure: %s", exc)
            self.state.status = PipelineStatus.PARTIAL_FAILURE
            self.state.add_error(str(exc))
            _db(lambda db: db_crud.record_error(db, self.session_id, str(exc), step="scene_videos"))

        except Exception as exc:
            logger.exception("Selective pipeline failed: %s", exc)
            self.state.status = PipelineStatus.ERROR
            self.state.add_error(str(exc))
            _db(lambda db: db_crud.record_error(db, self.session_id, str(exc), step="selective_pipeline"))

        finally:
            self._save()
            await self._upload_to_minio(str(self.state_path), "story_state.json")
            self._emit(ProgressEvent(
                "pipeline",
                self.state.status.value,
                message=f"Edit pipeline {self.state.status.value}",
            ))

        return self.state
