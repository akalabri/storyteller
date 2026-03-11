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

  // Shared session data passed between views
  const [sessionId, setSessionId] = useState(null);
  const [storyTitle, setStoryTitle] = useState(null);
  // true when re-entering CONVERSATION from RESULT (edit mode)
  const [isEditMode, setIsEditMode] = useState(false);
  const [devError, setDevError] = useState(null);

  useEffect(() => {
    getDevMode()
      .then(({ dev_mode, dev_session_id }) => {
        setDevMode(dev_mode);
        setDevSessionId(dev_session_id || 'dev_session');
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
  // In dev mode: skip conversation, fire the pipeline directly using the dev session.
  // In normal mode: go to the conversation view.
  const handleStart = async () => {
    if (devMode) {
      setDevError(null);
      try {
        const result = await startDevGeneration(devSessionId);
        setSessionId(result.session_id);
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
        />
      )}
      {viewState === 'RESULT' && (
        <ResultView
          sessionId={sessionId}
          storyTitle={storyTitle}
          onEdit={handleEdit}
        />
      )}
    </div>
  );
}

export default App;
