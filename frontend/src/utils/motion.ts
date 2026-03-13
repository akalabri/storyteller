// ============================================================
// Motion — mouse controls the wave: X tilts it, Y raises/lowers the middle
// ============================================================

const LERP = 0.18;

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

export function attachMotion(screen: HTMLElement): () => void {
  let targetX = 0.5;
  let targetY = 0.5;
  let currentX = 0.5;
  let currentY = 0.5;
  let raf: number | null = null;
  let waveDiv: HTMLElement | null = null;
  let wavePath: SVGPathElement | null = null;

  function findWave() {
    if (waveDiv && wavePath) return true;
    waveDiv = screen.querySelector<HTMLElement>(
      '.landing-wave-down, .conv-wave-down, .gen-wave-down, .story-wave-down, .gallery-wave-down'
    );
    if (waveDiv) {
      waveDiv.style.transform = '';
      wavePath = waveDiv.querySelector<SVGPathElement>('path');
    }
    return !!(waveDiv && wavePath);
  }

  function onMouseMove(e: MouseEvent) {
    targetX = e.clientX / window.innerWidth;
    targetY = e.clientY / window.innerHeight;
  }

  function tick() {
    if (findWave() && wavePath) {
      currentX = lerp(currentX, targetX, LERP);
      currentY = lerp(currentY, targetY, LERP);

      // X axis: tilts the wave left/right (see-saw)
      const tilt = (currentX - 0.5) * 320; // ±160

      // Y axis: pushes the middle of the wave up or down
      const midShift = (currentY - 0.5) * 160; // ±80

      const clamp = (v: number) => Math.round(Math.max(2, Math.min(88, v)));

      const leftY  = clamp(45 + tilt);
      const rightY = clamp(45 - tilt);
      const cp1Y   = clamp(85 - tilt * 0.6 + midShift);
      const cp2Y   = clamp(5  + tilt * 0.6 + midShift);

      wavePath.setAttribute(
        'd',
        `M0,${leftY} C480,${cp1Y} 960,${cp2Y} 1440,${rightY} L1440,90 L0,90 Z`
      );
    }

    raf = requestAnimationFrame(tick);
  }

  document.addEventListener('mousemove', onMouseMove);
  raf = requestAnimationFrame(tick);

  return () => {
    document.removeEventListener('mousemove', onMouseMove);
    if (raf !== null) cancelAnimationFrame(raf);
  };
}
