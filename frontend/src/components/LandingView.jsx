import React from 'react';
import HeroScrollSequence from './HeroScrollSequence';
import LandingCarousel from './LandingCarousel';
import './LandingView.css';

const LandingView = ({ onStart, devMode = false, devError = null }) => {
    return (
        <div className="landing-view-wrapper">
            <HeroScrollSequence />
            <LandingCarousel />

            {/* Fixed CTA Button that remains at the bottom of the screen */}
            <div className="fixed-cta-wrapper">
                {devMode && (
                    <div className="dev-mode-badge">
                        DEV MODE — skipping conversation
                    </div>
                )}
                {devError && (
                    <div className="dev-mode-error">{devError}</div>
                )}
                <button className="btn-primary glow-btn" onClick={onStart}>
                    {devMode ? 'Run Pipeline (Dev) ✦' : 'Generate Your Story ✦'}
                </button>
            </div>
        </div>
    );
};

export default LandingView;
