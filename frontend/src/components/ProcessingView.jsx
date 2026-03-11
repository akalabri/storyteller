import React, { useCallback, useEffect, useRef, useState } from 'react';
import { getState, openProgressSocket } from '../api/client';
import './ProcessingView.css';

/**
 * Maps a backend step key to a human-friendly status phrase.
 * Wildcards like "narration:1" match on the prefix before the colon.
 */
function stepToPhrase(step) {
    if (step === 'story_breakdown')   return 'Crafting your narrative…';
    if (step.startsWith('narration')) return 'Generating character voices…';
    if (step.startsWith('character')) return 'Painting character portraits…';
    if (step === 'visual_plan')       return 'Composing the visual plan…';
    if (step.startsWith('scene_image')) return 'Rendering scene illustrations…';
    if (step.startsWith('scene_video')) return 'Animating the scenes…';
    if (step === 'compile')           return 'Assembling the final video…';
    if (step === 'pipeline')          return 'Almost ready…';
    return 'Working…';
}

/**
 * Total expected steps for a typical story (used for progress %).
 * breakdown(1) + narration(N) + characters(M) + visual_plan(1) +
 * scene_images(N×3) + scene_videos(N×3) + compile(1)
 *
 * We start with a reasonable default (5 scenes × 3 sub-scenes = 15 each)
 * and refine once we know the actual scene count from state.
 */
function estimateTotalSteps(sceneCount = 5, charCount = 2) {
    return 1 + sceneCount + charCount + 1 + sceneCount * 3 + sceneCount * 3 + 1;
}

/**
 * ProcessingView
 *
 * Props:
 *   sessionId          — backend session id
 *   onFinish(storyTitle) — called when pipeline reports "done"
 *   pipelineStartedAt  — timestamp (ms) when the pipeline was kicked off.
 *                        Used to ignore a stale "done" state from a previous
 *                        run that is still sitting in the backend state.
 */
const ProcessingView = ({ sessionId, onFinish, pipelineStartedAt }) => {
    const [progress, setProgress] = useState(0);
    const [statusText, setStatusText] = useState('Connecting…');
    const [errorText, setErrorText] = useState(null);

    // Track completed steps to compute progress %
    const completedRef = useRef(0);
    const totalRef = useRef(estimateTotalSteps());
    const finishedRef = useRef(false);
    const pollTimerRef = useRef(null);

    const handleFinish = useCallback((state) => {
        if (finishedRef.current) return;
        finishedRef.current = true;
        setProgress(100);
        setStatusText('Your story is ready!');
        const firstScene = state?.breakdown?.story?.[0] ?? '';
        const title = firstScene.split('.')[0].trim().slice(0, 60) || 'Your Story';
        setTimeout(() => onFinish(title), 800);
    }, [onFinish]);

    // Poll the REST status endpoint as a fallback (or primary) mechanism.
    const startPolling = useCallback(() => {
        if (finishedRef.current) return;

        // Track whether we've seen the pipeline transition away from "done"
        // at least once (i.e. it went to "running") so we know a fresh run started.
        let seenRunning = false;

        const poll = async () => {
            if (finishedRef.current) return;
            try {
                const state = await getState(sessionId);
                const sceneCount = state.breakdown?.story?.length ?? 5;
                const charCount = state.breakdown?.characters_prompts?.length ?? 2;
                totalRef.current = estimateTotalSteps(sceneCount, charCount);

                const completedSteps = (state.steps ?? []).filter(
                    (s) => s.status === 'done' || s.status === 'failed' || s.status === 'skipped'
                ).length;
                completedRef.current = completedSteps;
                const pct = Math.min(99, (completedSteps / totalRef.current) * 100);
                setProgress(pct);

                // Find the most recent running step for status text
                const running = (state.steps ?? []).find((s) => s.status === 'running');
                if (running) {
                    setStatusText(stepToPhrase(running.step));
                    seenRunning = true;
                }

                if (state.status === 'running') seenRunning = true;

                // Only treat "done" as finished if we've seen the pipeline
                // actively running since this view mounted, OR if pipelineStartedAt
                // is null (legacy path without timestamp).
                if (state.status === 'done' && (seenRunning || !pipelineStartedAt)) {
                    handleFinish(state);
                    return;
                }
                if (state.status === 'error') {
                    setErrorText((state.errors ?? []).join(' ') || 'Pipeline failed. Check the backend logs.');
                    return;
                }
            } catch {
                // Backend may not be ready yet — keep polling
            }
            pollTimerRef.current = setTimeout(poll, 3000);
        };

        poll();
    }, [sessionId, handleFinish, pipelineStartedAt]);

    useEffect(() => {
        if (!sessionId) return;

        // Fetch state immediately — gives accurate step count.
        // We do NOT treat a "done" status here as a signal to finish, because
        // it could be stale from a previous pipeline run that completed before
        // this view mounted (e.g. after an edit). We only finish on a fresh
        // "done" event from the WebSocket or a poll that runs after mount.
        getState(sessionId)
            .then((state) => {
                const sceneCount = state.breakdown?.story?.length ?? 5;
                const charCount = state.breakdown?.characters_prompts?.length ?? 2;
                totalRef.current = estimateTotalSteps(sceneCount, charCount);
            })
            .catch(() => { /* use default estimate */ });

        // Track whether we've seen any "running" step event since mounting.
        // This prevents a stale "pipeline done" event (replayed from a previous
        // run) from immediately resolving the view before the new run starts.
        let wsSeenRunning = false;

        const closeSocket = openProgressSocket(
            sessionId,
            (event) => {
                const { step, status, message } = event;

                if (status === 'running') {
                    wsSeenRunning = true;
                    setStatusText(stepToPhrase(step));
                }

                if (status === 'done' || status === 'failed' || status === 'skipped') {
                    completedRef.current += 1;
                    const pct = Math.min(
                        99,
                        (completedRef.current / totalRef.current) * 100
                    );
                    setProgress(pct);
                }

                if (status === 'failed') {
                    setStatusText(`${stepToPhrase(step)} (retrying…)`);
                }

                // Pipeline terminal events
                if (step === 'pipeline') {
                    if (status === 'done' && (wsSeenRunning || !pipelineStartedAt)) {
                        getState(sessionId)
                            .then((state) => handleFinish(state))
                            .catch(() => handleFinish(null));
                    } else if (status === 'error') {
                        setErrorText(message || 'Pipeline failed. Check the backend logs.');
                    }
                }
            },
            () => {
                // WebSocket closed — fall back to polling so the user isn't stuck
                if (!finishedRef.current) {
                    setStatusText('Working on your story…');
                    startPolling();
                }
            }
        );

        return () => {
            closeSocket();
            if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
        };
    }, [sessionId, handleFinish, startPolling]);

    return (
        <div className="view-container processing-container">
            <div className="processing-content">
                <div className="loading-spinner">
                    <div className="spinner-core"></div>
                </div>

                <h2 className="ethereal-text">{statusText}</h2>

                {errorText ? (
                    <p className="processing-error">{errorText}</p>
                ) : (
                    <>
                        <div className="progress-wrapper">
                            <div className="progress-track">
                                <div
                                    className="progress-fill"
                                    style={{ width: `${progress}%` }}
                                >
                                    <div className="progress-glow"></div>
                                </div>
                            </div>
                            <div className="progress-particles" style={{ width: `${progress}%` }}></div>
                        </div>

                        <div className="percentage-text">
                            {Math.floor(progress)}%
                        </div>
                    </>
                )}
            </div>
        </div>
    );
};

export default ProcessingView;
