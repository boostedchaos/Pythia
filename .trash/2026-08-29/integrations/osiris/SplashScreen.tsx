'use client';

/** Opening screen — glowing veins erupt from the center and branch outward,
 *  consuming the screen, while PYTHIA resolves in the middle (Doto, regular). */
import { useEffect, useRef } from 'react';
import { motion } from 'framer-motion';

export default function SplashScreen() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const W = (canvas.width = Math.floor(window.innerWidth * dpr));
    const H = (canvas.height = Math.floor(window.innerHeight * dpr));
    canvas.style.width = window.innerWidth + 'px';
    canvas.style.height = window.innerHeight + 'px';
    const cx = W / 2, cy = H / 2;
    const maxR = Math.hypot(cx, cy);

    // violet core -> cyan tips, by distance from center
    const A = [154, 123, 255], B = [45, 245, 200];
    const col = (t: number, a: number) =>
      `rgba(${Math.round(A[0] + (B[0] - A[0]) * t)},${Math.round(A[1] + (B[1] - A[1]) * t)},${Math.round(A[2] + (B[2] - A[2]) * t)},${a})`;

    type Tip = { x: number; y: number; px: number; py: number; ang: number; w: number; gen: number; life: number; speed: number };
    const tips: Tip[] = [];
    const spawn = (x: number, y: number, ang: number, w: number, gen: number) => {
      if (tips.length > 420) return;
      tips.push({ x, y, px: x, py: y, ang, w, gen, life: 70 + Math.random() * 90, speed: (2.7 + Math.random() * 1.9) * dpr });
    };
    const TRUNKS = 7;
    for (let i = 0; i < TRUNKS; i++) spawn(cx, cy, (i / TRUNKS) * Math.PI * 2 + Math.random() * 0.5, 3.4 * dpr, 0);

    ctx.fillStyle = '#08060F';
    ctx.fillRect(0, 0, W, H);
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineCap = 'round';

    let raf = 0, frame = 0;
    const step = () => {
      frame++;
      for (let i = tips.length - 1; i >= 0; i--) {
        const t = tips[i];
        t.px = t.x; t.py = t.y;
        t.ang += (Math.random() - 0.5) * 0.55;                 // meander
        t.x += Math.cos(t.ang) * t.speed;
        t.y += Math.sin(t.ang) * t.speed;
        const tc = Math.min(1, Math.hypot(t.x - cx, t.y - cy) / maxR);

        ctx.beginPath();
        ctx.moveTo(t.px, t.py);
        ctx.lineTo(t.x, t.y);
        ctx.strokeStyle = col(tc, 0.55);
        ctx.lineWidth = Math.max(0.4, t.w);
        ctx.shadowBlur = 6 * dpr;
        ctx.shadowColor = col(tc, 0.7);
        ctx.stroke();

        t.w *= 0.991;                                          // taper toward capillaries
        t.life--;

        if (t.gen < 6 && Math.random() < 0.062 && t.w > 0.9 * dpr) {  // branch
          const off = (0.4 + Math.random() * 0.6) * (Math.random() < 0.5 ? 1 : -1);
          spawn(t.x, t.y, t.ang + off, t.w * 0.72, t.gen + 1);
          ctx.beginPath();
          ctx.arc(t.x, t.y, t.w * 0.8, 0, Math.PI * 2);
          ctx.fillStyle = col(tc, 0.5);
          ctx.fill();
        }
        if (t.life <= 0 || t.w < 0.4 * dpr || t.x < -30 || t.x > W + 30 || t.y < -30 || t.y > H + 30) tips.splice(i, 1);
      }
      ctx.shadowBlur = 0;
      if (tips.length > 0 && frame < 460) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.6 }}
      className="fixed inset-0 z-[9999] overflow-hidden"
      style={{ background: '#08060F' }}
    >
      <canvas ref={ref} className="absolute inset-0" />
      {/* keep the center readable as the veins erupt from behind the word */}
      <div className="absolute inset-0 pointer-events-none"
        style={{ background: 'radial-gradient(ellipse 52% 27% at center, rgba(8,6,15,0.97) 0%, rgba(8,6,15,0.92) 44%, rgba(8,6,15,0.55) 68%, transparent 100%)' }} />
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <motion.h1
          initial={{ opacity: 0, letterSpacing: '0.62em' }}
          animate={{ opacity: 1, letterSpacing: '0.3em' }}
          transition={{ duration: 1.3, delay: 0.35, ease: [0.16, 1, 0.3, 1] }}
          style={{
            fontFamily: 'var(--font-doto)', fontWeight: 400,
            fontSize: 'clamp(40px, 12vw, 120px)', paddingLeft: '0.3em',
            color: 'var(--gold-primary)', textShadow: '0 0 32px rgba(154,123,255,0.55)',
          }}
        >
          PYTHIA
        </motion.h1>
      </div>
    </motion.div>
  );
}
