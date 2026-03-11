import React from 'react';
import HeroScrollSequence from './HeroScrollSequence';
import LandingCarousel from './LandingCarousel';
import './LandingView.css';

const LandingView = ({ onStart, devMode = false, devSteps = [], devError = null }) => {
    const isEditingStep = devMode && devSteps.includes('editing');

    const devBadgeText = isEditingStep
        ? 'DEV MODE — editing flow'
        : 'DEV MODE — skipping conversation';

    const buttonLabel = isEditingStep
        ? 'Edit Story (Dev) ✦'
        : devMode
            ? 'Run Pipeline (Dev) ✦'
            : 'Generate Your Story ✦';

    return (
        <div className="landing-view-wrapper">
            <HeroScrollSequence />
            <LandingCarousel />

            {/* Fixed CTA Button that remains at the bottom of the screen */}
            <div className="fixed-cta-wrapper">
                {devMode && (
                    <div className="dev-mode-badge">
                        {devBadgeText}
                    </div>
                )}
                {devError && (
                    <div className="dev-mode-error">{devError}</div>
                )}
                <button className="btn-primary glow-btn" onClick={onStart}>
                    {buttonLabel}
                </button>
            </div>
        </div>
    );
};

export default LandingView;
