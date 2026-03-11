import React, { useEffect, useRef, useState } from 'react';
import { videoUrl } from '../api/client';
import './ResultView.css';

/**
 * ResultView
 *
 * Displays the final compiled story video and action buttons.
 *
 * Props:
 *   sessionId  — used to build the video stream URL
 *   storyTitle — title derived from the story breakdown
 *   onEdit     — called when user clicks "Edit via Conversation"
 */
const ResultView = ({ sessionId, storyTitle, onEdit, pipelineStartedAt }) => {
    const videoRef = useRef(null);
    const [isPlaying, setIsPlaying] = useState(false);
    const [timelineProgress, setTimelineProgress] = useState(0);

    // Append a cache-busting query param so the browser always fetches the
    // freshly compiled video rather than serving a cached copy from a prior run.
    const src = sessionId
        ? `${videoUrl(sessionId)}?t=${pipelineStartedAt ?? 0}`
        : null;

    // Sync play/pause state with the native video element
    const handlePlayToggle = () => {
        const video = videoRef.current;
        if (!video) return;
        if (video.paused) {
            video.play().catch(console.error);
        } else {
            video.pause();
        }
    };

    // Keep isPlaying in sync with native events (e.g. video ends)
    useEffect(() => {
        const video = videoRef.current;
        if (!video) return;

        const onPlay  = () => setIsPlaying(true);
        const onPause = () => setIsPlaying(false);
        const onEnded = () => { setIsPlaying(false); setTimelineProgress(0); };

        video.addEventListener('play',  onPlay);
        video.addEventListener('pause', onPause);
        video.addEventListener('ended', onEnded);

        return () => {
            video.removeEventListener('play',  onPlay);
            video.removeEventListener('pause', onPause);
            video.removeEventListener('ended', onEnded);
        };
    }, []);

    // Update the custom timeline bar as the video plays
    const handleTimeUpdate = () => {
        const video = videoRef.current;
        if (!video || !video.duration) return;
        setTimelineProgress((video.currentTime / video.duration) * 100);
    };

    // Seek on timeline click
    const handleTimelineClick = (e) => {
        const video = videoRef.current;
        if (!video || !video.duration) return;
        const rect = e.currentTarget.getBoundingClientRect();
        const ratio = (e.clientX - rect.left) / rect.width;
        video.currentTime = ratio * video.duration;
    };

    const displayTitle = storyTitle || 'Your Story';

    return (
        <div className="view-container result-container">
            <div className="result-header">
                <h2 className="text-gradient result-title">Your Masterpiece</h2>
                <p className="result-subtitle">{displayTitle}</p>
            </div>

            <div className="video-player-container">
                <div className="video-viewport" onClick={handlePlayToggle}>
                    {/* Real video element */}
                    {src ? (
                        <video
                            ref={videoRef}
                            src={src}
                            className="story-video"
                            onTimeUpdate={handleTimeUpdate}
                            playsInline
                        />
                    ) : (
                        /* Fallback placeholder if no session yet */
                        <div className="video-placeholder"></div>
                    )}

                    <div className="glass-overlay"></div>

                    {/* Custom play button — hidden while playing */}
                    {!isPlaying && (
                        <div className="play-button-wrapper">
                            <div className="play-button">
                                <div className="play-icon"></div>
                            </div>
                        </div>
                    )}

                    {/* Custom timeline */}
                    <div className="video-controls" onClick={(e) => e.stopPropagation()}>
                        <div className="timeline" onClick={handleTimelineClick}>
                            <div
                                className="timeline-progress"
                                style={{ width: `${timelineProgress}%`, transition: isPlaying ? 'width 0.25s linear' : 'none' }}
                            ></div>
                        </div>
                    </div>
                </div>
            </div>

            <div className="action-container result-actions">
                <button className="btn-secondary glow-on-hover" onClick={onEdit}>
                    <span className="icon">✎</span> Edit via Conversation
                </button>
                <button className="btn-primary share-btn" onClick={() => {
                    if (src) window.open(src, '_blank');
                }}>
                    Share Story ⇪
                </button>
            </div>
        </div>
    );
};

export default ResultView;
