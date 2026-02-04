import React, {useMemo} from 'react';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {loadFont} from '@remotion/google-fonts/Manrope';

loadFont();

export type OnboardingAICoachProps = {
  title: string;
  bodyA: string;
  bodyB: string;
  logoSrc: string | null;
};

type Point = {x: number; y: number};

type FlightGroup = {
  cells: number[];
  start: number;
  end: number;
  target: Point;
};

const clampFade = (frame: number, start: number, end: number) =>
  interpolate(frame, [start, end], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

export const OnboardingAICoach: React.FC<OnboardingAICoachProps> = ({
  title,
  bodyA,
  bodyB,
  logoSrc,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();

  const resolvedLogoSrc =
    logoSrc && (logoSrc.startsWith('http') || logoSrc.startsWith('data:') || logoSrc.startsWith('/'))
      ? logoSrc
      : logoSrc
        ? staticFile(logoSrc)
        : null;

  const intro = spring({
    frame,
    fps,
    config: {damping: 14, stiffness: 120, mass: 0.9},
  });

  const fade = clampFade(frame, 0, 18);
  const textIn = clampFade(frame, 18, 46);
  const textY = interpolate(frame, [18, 46], [20, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const switchStart = 90;
  const switchMid = 104;
  const switchEnd = 112;

  const bodyAOpacity = interpolate(frame, [18, 40, switchStart, switchMid], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const bodyBOpacity = interpolate(frame, [switchMid, switchEnd, durationInFrames], [0, 1, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const bodyAY = interpolate(frame, [switchStart, switchMid], [0, -10], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const bodyBY = interpolate(frame, [switchMid, switchEnd], [10, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const gridIntroOpacity = clampFade(frame, 18, 36);
  const gridScale = interpolate(frame, [18, 36], [0.96, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const floatY = Math.sin(frame / 26) * 6;

  const glowPulse = interpolate(
    frame,
    [0, durationInFrames * 0.45, durationInFrames * 0.72, durationInFrames],
    [0.72, 1, 0.86, 1],
  );

  const sceneCenterX = 260;
  const mascotCenter: Point = {x: sceneCenterX, y: 90};

  const extractionStart = 88;
  const extractionEnd = 104;

  const focusDim = interpolate(frame, [extractionStart, 140], [1, 0.55], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const selectedDim = interpolate(frame, [extractionStart, extractionEnd], [1, 0.2], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const highlightGroups = [
    {cells: [0, 4, 8], start: 22, end: 38},
    {cells: [1, 5, 9], start: 38, end: 54},
    {cells: [2, 6, 10], start: 54, end: 70},
    {cells: [3, 7, 11], start: 70, end: 86},
  ];

  const flightGroups: FlightGroup[] = [
    {cells: [0, 4, 8], start: 92, end: 110, target: {x: sceneCenterX - 48, y: 88}},
    {cells: [1, 5, 9], start: 100, end: 118, target: {x: sceneCenterX - 16, y: 88}},
    {cells: [2, 6, 10], start: 108, end: 126, target: {x: sceneCenterX + 16, y: 88}},
    {cells: [3, 7, 11], start: 116, end: 134, target: {x: sceneCenterX + 48, y: 88}},
  ];

  const selectedCells = useMemo(() => new Set(flightGroups.flatMap((group) => group.cells)), []);

  const pulse = flightGroups.reduce((acc, group) => {
    const p = spring({
      frame: Math.max(0, frame - group.end),
      fps,
      config: {damping: 12, stiffness: 200, mass: 0.6},
    });
    return acc + p;
  }, 0);
  const pulseClamped = Math.min(1, pulse);

  const mascotBreath = Math.sin(frame / 18) * 0.015;
  const mascotScale = 1 + mascotBreath + pulseClamped * 0.06;

  const mascotGlow = 0.6 + mascotBreath * 0.2 + pulseClamped * 0.5;


  const card = {width: 620, height: 296, centerX: 260, centerY: 314};
  const cardLeft = card.centerX - card.width / 2;
  const cardTop = card.centerY - card.height / 2;
  const grid = {left: 22, top: 44, right: 22, bottom: 44};
  const gridWidth = card.width - grid.left - grid.right;
  const gridHeight = card.height - grid.top - grid.bottom;
  const gap = 12;
  const cols = 4;
  const rows = 3;
  const cellWidth = (gridWidth - gap * (cols - 1)) / cols;
  const cellHeight = (gridHeight - gap * (rows - 1)) / rows;

  const cellCenters = useMemo(() => {
    return Array.from({length: cols * rows}).map((_, idx) => {
      const row = Math.floor(idx / cols);
      const col = idx % cols;
      return {
        x: cardLeft + grid.left + col * (cellWidth + gap) + cellWidth / 2,
        y: cardTop + grid.top + row * (cellHeight + gap) + cellHeight / 2,
      };
    });
  }, [cardLeft, cardTop, cellWidth, cellHeight, grid.left, grid.top, gap]);

  return (
    <AbsoluteFill
      style={{
        background:
          'radial-gradient(1100px 1100px at 20% 15%, #15112D 0%, #0B0A17 55%, #070612 100%)',
        color: '#F3EEFF',
        fontFamily: 'Manrope, system-ui, sans-serif',
        padding: '120px 110px',
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage:
            'linear-gradient(rgba(114, 92, 255, 0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(114, 92, 255, 0.06) 1px, transparent 1px)',
          backgroundSize: '120px 120px',
          opacity: 0.14,
          transform: `translate(${interpolate(frame, [0, durationInFrames], [0, 40])}px, ${interpolate(
            frame,
            [0, durationInFrames],
            [0, 40],
          )}px)`,
        }}
      />

      <div
        style={{
          position: 'absolute',
          left: '50%',
          top: '37%',
          width: 520,
          height: 520,
          transform: `translate(-50%, -50%) scale(${0.9 + 0.1 * intro})`,
          opacity: fade,
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 0,
            borderRadius: '50%',
            background:
              'radial-gradient(circle, rgba(109,75,255,0.35) 0%, rgba(75,108,255,0.15) 55%, rgba(11,10,23,0) 75%)',
            filter: `blur(${26 * glowPulse}px)`,
            opacity: 0.7,
          }}
        />

        <div
          style={{
            position: 'absolute',
            left: mascotCenter.x,
            top: mascotCenter.y,
            transform: `translate(-50%, -50%) scale(${mascotScale})`,
            width: 140,
            height: 140,
          }}
        >
          <div
            style={{
              position: 'absolute',
              inset: 6,
              borderRadius: '50%',
              background: 'radial-gradient(circle, rgba(109,75,255,0.65), rgba(70,55,160,0.15))',
              filter: `blur(${18 + mascotGlow * 16}px)`,
              opacity: 0.8,
            }}
          />
          {resolvedLogoSrc ? (
            <img
              src={resolvedLogoSrc}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'contain',
                filter: 'drop-shadow(0 0 18px rgba(109, 75, 255, 0.6))',
              }}
            />
          ) : (
            <div
              style={{
                position: 'absolute',
                inset: 18,
                borderRadius: '50%',
                background:
                  'radial-gradient(70% 70% at 30% 25%, rgba(196, 173, 255, 0.95) 0%, rgba(118, 89, 255, 0.95) 55%, rgba(59, 64, 126, 0.95) 100%)',
                boxShadow: '0 0 30px rgba(109, 75, 255, 0.7)',
              }}
            >
              <div
                style={{
                  position: 'absolute',
                  left: 32,
                  top: 46,
                  width: 14,
                  height: 14,
                  borderRadius: '50%',
                  background: 'rgba(243, 238, 255, 0.95)',
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  right: 32,
                  top: 46,
                  width: 14,
                  height: 14,
                  borderRadius: '50%',
                  background: 'rgba(243, 238, 255, 0.95)',
                }}
              />
            </div>
          )}
        </div>

        <div
          style={{
            position: 'absolute',
            left: '50%',
            top: 314,
            width: 620,
            height: 296,
            transform: `translate(-50%, -50%) translateY(${floatY}px)`,
            borderRadius: 24,
            background:
              'linear-gradient(180deg, rgba(15, 12, 32, 0.92) 0%, rgba(11, 10, 23, 0.92) 100%)',
            border: '1px solid rgba(123, 100, 255, 0.28)',
            boxShadow: '0 18px 40px rgba(8, 6, 18, 0.6)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              position: 'absolute',
              inset: 0,
              background:
                'linear-gradient(180deg, rgba(109, 75, 255, 0.12) 0%, rgba(11, 10, 23, 0) 65%)',
              opacity: 0.9,
            }}
          />
          <div
            style={{
              position: 'absolute',
              inset: 0,
              background:
                'radial-gradient(800px 260px at 30% 0%, rgba(109, 75, 255, 0.12) 0%, rgba(11, 10, 23, 0) 60%)',
              opacity: 0.85,
            }}
          />

          <div
            style={{
              position: 'absolute',
              left: grid.left,
              right: grid.right,
              top: grid.top,
              bottom: grid.bottom,
              opacity: gridIntroOpacity,
              transform: `scale(${gridScale})`,
              transformOrigin: 'center',
            }}
          >
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gridTemplateRows: 'repeat(3, 1fr)',
                gap: 12,
              }}
            >
              {Array.from({length: 12}).map((_, idx) => {
                const isSelected = selectedCells.has(idx);
                const baseAlpha = 0.1 + (idx % 3) * 0.015;
                const highlightBoost = highlightGroups.reduce((acc, group) => {
                  if (!group.cells.includes(idx)) {
                    return acc;
                  }
                  const on = interpolate(frame, [group.start, group.end], [0, 1], {
                    extrapolateLeft: 'clamp',
                    extrapolateRight: 'clamp',
                  });
                  const pulse = 0.45 + 0.35 * Math.sin((frame - group.start) / 6);
                  return Math.max(acc, on * pulse);
                }, 0);
                const dim = isSelected ? selectedDim : focusDim;
                const alpha = (baseAlpha + highlightBoost * 0.2) * dim;
                const shadow = (highlightBoost * 0.7 + (isSelected ? 0.2 : 0)) * dim;
                return (
                  <div
                    key={`cell-${idx}`}
                    style={{
                      borderRadius: 10,
                      background: `rgba(243, 238, 255, ${alpha})`,
                      border: '1px solid rgba(120, 96, 255, 0.25)',
                      boxShadow:
                        shadow > 0.02
                          ? `0 0 ${10 + shadow * 18}px rgba(109, 75, 255, ${0.1 + shadow * 0.3})`
                          : 'none',
                      overflow: 'hidden',
                      position: 'relative',
                    }}
                  >
                    <div
                      style={{
                        position: 'absolute',
                        left: 10,
                        top: 10,
                        height: 6,
                        width: `${(0.55 + ((idx * 37) % 30) / 100) * 100}%`,
                        borderRadius: 6,
                        background: 'rgba(243, 238, 255, 0.16)',
                      }}
                    />
                    <div
                      style={{
                        position: 'absolute',
                        left: 10,
                        bottom: 10,
                        height: 6,
                        width: `${(0.35 + ((idx * 19) % 40) / 100) * 100}%`,
                        borderRadius: 6,
                        background: 'rgba(243, 238, 255, 0.12)',
                      }}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            width: 520,
            height: 520,
            pointerEvents: 'none',
          }}
        >
          {flightGroups.flatMap((group, groupIdx) =>
            group.cells.map((cellIdx, idx) => {
              const start = cellCenters[cellIdx];
              const t = interpolate(frame, [group.start, group.end], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
                easing: Easing.inOut(Easing.cubic),
              });
              const arc = Math.sin(Math.PI * t) * 18;
              const x = start.x + (group.target.x - start.x) * t;
              const y = start.y + (group.target.y - start.y) * t - arc;
              const opacity = interpolate(
                frame,
                [group.start - 6, group.start, group.end - 4, group.end],
                [0, 1, 1, 0],
                {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                },
              );
              const scale = interpolate(t, [0, 1], [1, 0.7], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              });
              return (
                <div
                  key={`bar-${groupIdx}-${idx}`}
                  style={{
                    position: 'absolute',
                    left: x,
                    top: y,
                    width: 48,
                    height: 6,
                    borderRadius: 6,
                    background: 'rgba(243, 238, 255, 0.55)',
                    boxShadow: '0 0 12px rgba(109, 75, 255, 0.5)',
                    opacity,
                    transform: `translate(-50%, -50%) scale(${scale})`,
                  }}
                />
              );
            }),
          )}
        </div>

      </div>

      <div
        style={{
          position: 'absolute',
          bottom: 80,
          left: 110,
          right: 110,
          opacity: textIn,
          transform: `translateY(${textY}px)`,
        }}
      >
        <div
          style={{
            fontSize: 74,
            fontWeight: 700,
            letterSpacing: 0.4,
            marginBottom: 20,
          }}
        >
          {title}
        </div>
        <div style={{position: 'relative', minHeight: 170}}>
          <div
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              fontSize: 34,
              lineHeight: 1.5,
              color: 'rgba(227, 220, 255, 0.85)',
              whiteSpace: 'pre-line',
              opacity: bodyAOpacity,
              transform: `translateY(${bodyAY}px)`,
            }}
          >
            {bodyA}
          </div>
          <div
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              fontSize: 34,
              lineHeight: 1.5,
              color: 'rgba(227, 220, 255, 0.85)',
              whiteSpace: 'pre-line',
              opacity: bodyBOpacity,
              transform: `translateY(${bodyBY}px)`,
            }}
          >
            {bodyB}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
