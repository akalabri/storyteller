import React, { useEffect, useRef, useState } from 'react';
import './HeroScrollSequence.css';

const FRAME_COUNT = 80;

const HeroScrollSequence = () => {
    const canvasRef = useRef(null);
    const containerRef = useRef(null);
    const [images, setImages] = useState([]);

    useEffect(() => {
        // Preload images
        const loadedImages = [];
        let loadedCount = 0;

        for (let i = 0; i < FRAME_COUNT; i++) {
            const img = new Image();
            // Format number to 3 digits (e.g., 000, 001, 010)
            const number = i.toString().padStart(3, '0');
            img.src = `/assets/hero/Elements_gather_and_merge_swirl_af3f3f1d4f_${number}.jpg`;
            img.onload = () => {
                loadedCount++;
                if (i === 0) {
                    drawFrame(0);
                }
                if (loadedCount === FRAME_COUNT) {
                    window.dispatchEvent(new Event('scroll'));
                }
            };
            loadedImages.push(img);
        }
        setImages(loadedImages);
    }, []);

    const drawFrame = (frameIndex) => {
        if (!canvasRef.current || !images[frameIndex]) return;
        const canvas = canvasRef.current;
        const ctx = canvas.getContext('2d');

        // Calculate aspect ratio to cover canvas
        const img = images[frameIndex];
        const canvasRatio = canvas.width / canvas.height;
        const imgRatio = img.width / img.height;

        let drawWidth, drawHeight, offsetX = 0, offsetY = 0;

        if (canvasRatio > imgRatio) {
            drawWidth = canvas.width;
            drawHeight = canvas.width / imgRatio;
            offsetY = (canvas.height - drawHeight) / 2;
        } else {
            drawHeight = canvas.height;
            drawWidth = canvas.height * imgRatio;
            offsetX = (canvas.width - drawWidth) / 2;
        }

        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, offsetX, offsetY, drawWidth, drawHeight);
    };

    useEffect(() => {
        const handleScroll = () => {
            if (!containerRef.current || images.length === 0) return;

            const container = containerRef.current;
            const rect = container.getBoundingClientRect();
            const scrollPosition = -rect.top;
            const scrollHeight = rect.height - window.innerHeight;

            if (scrollPosition >= 0 && scrollPosition <= scrollHeight) {
                const scrollFraction = scrollPosition / scrollHeight;
                const frameIndex = Math.min(
                    FRAME_COUNT - 1,
                    Math.floor(scrollFraction * FRAME_COUNT)
                );
                drawFrame(frameIndex);
            } else if (scrollPosition < 0) {
                drawFrame(0);
            } else {
                drawFrame(FRAME_COUNT - 1);
            }
        };

        window.addEventListener('scroll', handleScroll);
        return () => window.removeEventListener('scroll', handleScroll);
    }, [images]);

    useEffect(() => {
        const handleResize = () => {
            if (canvasRef.current) {
                canvasRef.current.width = window.innerWidth;
                canvasRef.current.height = window.innerHeight;
                // redraw current frame based on scroll
                window.dispatchEvent(new Event('scroll'));
            }
        };

        window.addEventListener('resize', handleResize);
        handleResize(); // Initial resize

        return () => window.removeEventListener('resize', handleResize);
    }, []);

    return (
        <div className="hero-scroll-container" ref={containerRef}>
            <div className="sticky-canvas-container">
                <canvas ref={canvasRef} className="hero-canvas"></canvas>
                <div className="hero-overlay">
                    <h1 className="hero-title text-gradient">Story Vibe AI from Aflah xxxxxxxxx</h1>
                </div>
            </div>
        </div>
    );
};

export default HeroScrollSequence;
