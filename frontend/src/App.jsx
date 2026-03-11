import React, { useState, useEffect } from 'react';
import LandingView from './components/LandingView';
import ConversationView from './components/ConversationView';
import ProcessingView from './components/ProcessingView';
import ResultView from './components/ResultView';
import { startDevGeneration, getDevMode, trackPage } from './api/client';

// App States: LANDING, CONVERSATION, PROCESSING, RESULT
function App() {
  const [viewState, setViewState] = useState('LANDING');

  // Dev mode: fetched from backend (single source of truth: backend .env DEV_MODE)
  const [devMode, setDevMode] = useState(false);
  const [devSessionId, setDevSessionId] = useState('dev_session');
  // dev_steps array from backend — used to route the dev button behaviour.
  // When it contains 'editing', the dev button goes straight to the editing UI.
  const [devSteps, setDevSteps] = useState([]);

  // Shared session data passed between views
  const [sessionId, setSessionId] = useState(null);
  const [storyTitle, setStoryTitle] = useState(null);
  // true when re-entering CONVERSATION from RESULT (edit mode)
  const [isEditMode, setIsEditMode] = useState(false);
  const [devError, setDevError] = useState(null);
  // Timestamp set each time we kick off a new pipeline run.
  // ProcessingView uses it to ignore stale "done" state from a previous run.
  // ResultView uses it as a cache-buster on the video URL.
  const [pipelineStartedAt, setPipelineStartedAt] = useState(null);

  useEffect(() => {
    getDevMode()
      .then(({ dev_mode, dev_session_id, dev_steps }) => {
        setDevMode(dev_mode);
        setDevSessionId(dev_session_id || 'dev_session');
        setDevSteps(Array.isArray(dev_steps) ? dev_steps : []);
      })
      .catch(() => {
        setDevMode(false);
      });
    // Track initial landing page visit
    trackPage('LANDING', null);
  }, []);

  const transitionTo = (newState) => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    setViewState(newState);
    // Track page navigation (sessionId may be null for early transitions)
    trackPage(newState, sessionId);
  };

  // Called when the user clicks "Generate" on the landing page.
  // In dev mode with DEV_STEPS=editing: go straight to the editing UI using the dev session.
  // In dev mode (other steps): skip conversation, fire the pipeline directly.
  // In normal mode: go to the conversation view.
  const handleStart = async () => {
    if (devMode && devSteps.includes('editing')) {
      // Jump straight to editing — use the dev session as the base state.
      setSessionId(devSessionId);
      setIsEditMode(true);
      transitionTo('CONVERSATION');
    } else if (devMode) {
      setDevError(null);
      try {
        const result = await startDevGeneration(devSessionId);
        setSessionId(result.session_id);
        setPipelineStartedAt(Date.now());
        transitionTo('PROCESSING');
      } catch (err) {
        console.error('[DevMode] startDevGeneration failed:', err);
        setDevError(err.message || 'Failed to start dev generation.');
      }
    } else {
      transitionTo('CONVERSATION');
    }
  };

  // ConversationView calls this when the user triggers generation/edit.
  // It receives the session_id returned by the backend.
  const handleConversationComplete = (sid) => {
    setSessionId(sid);
    setIsEditMode(false);
    setPipelineStartedAt(Date.now());
    transitionTo('PROCESSING');
  };

  // ProcessingView calls this once the pipeline reports "done".
  // It receives the story title extracted from the state.
  const handleProcessingFinish = (title) => {
    setStoryTitle(title);
    transitionTo('RESULT');
  };

  // ResultView calls this when the user clicks "Edit via Conversation".
  const handleEdit = () => {
    setIsEditMode(true);
    transitionTo('CONVERSATION');
  };

  return (
    <div className={`app-container ${viewState}`}>
      {viewState === 'LANDING' && (
        <LandingView
          onStart={handleStart}
          devMode={devMode}
          devSteps={devSteps}
          devError={devError}
        />
      )}
      {viewState === 'CONVERSATION' && (
        <ConversationView
          onComplete={handleConversationComplete}
          sessionId={sessionId}
          isEditMode={isEditMode}
        />
      )}
      {viewState === 'PROCESSING' && (
        <ProcessingView
          sessionId={sessionId}
          onFinish={handleProcessingFinish}
          pipelineStartedAt={pipelineStartedAt}
        />
      )}
      {viewState === 'RESULT' && (
        <ResultView
          sessionId={sessionId}
          storyTitle={storyTitle}
          onEdit={handleEdit}
          pipelineStartedAt={pipelineStartedAt}
        />
      )}
    </div>
  );
}

export default App;
