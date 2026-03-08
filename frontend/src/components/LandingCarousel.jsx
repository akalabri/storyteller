import React from 'react';
import './LandingCarousel.css';

const MOCK_STORIES = [
    { id: 1, title: 'The Cybernetic Dawn', desc: 'A rogue AI discovers emotion.', image: 'url(/assets/thumnail_mockup.png)' },
    { id: 2, title: 'Echoes of Eternity', desc: 'Timeless love across dimensions.', image: 'url(/assets/thumnail_mockup.png)' },
    { id: 3, title: 'Neon Shadows', desc: 'A detective in a dystopian future.', image: 'url(/assets/thumnail_mockup.png)' },
    { id: 4, title: 'Whispers from the Void', desc: 'Space explorers find something ancient.', image: 'url(/assets/thumnail_mockup.png)' },
    { id: 5, title: 'The Last Oasis', desc: 'Survival in a desolate wasteland.', image: 'url(/assets/thumnail_mockup.png)' },
];

const LandingCarousel = () => {
    const theta = 360 / MOCK_STORIES.length;
    const radius = 280;

    return (
        <div className="landing-container">
            <div className="carousel-scene">
                <div className="carousel-spinner">
                    {MOCK_STORIES.map((story, index) => {
                        const angle = theta * index;
                        return (
                            <div
                                key={story.id}
                                className="carousel-card"
                                style={{
                                    transform: `rotateY(${angle}deg) translateZ(${radius}px)`
                                }}
                            >
                                <div className="card-image" style={{ backgroundImage: story.image }}></div>
                                <div className="card-content">
                                    <h3 className="card-title">{story.title}</h3>
                                    <p className="card-desc">{story.desc}</p>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
};

export default LandingCarousel;
