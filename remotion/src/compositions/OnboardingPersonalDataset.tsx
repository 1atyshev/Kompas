import React, {useMemo} from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {loadFont} from '@remotion/google-fonts/Manrope';

loadFont();

export type OnboardingPersonalDatasetProps = {
  title: string;
  bodyA: string;
  bodyB: string;
  badgeA: string;
  badgeB: string;
};

export const OnboardingPersonalDataset: React.FC<OnboardingPersonalDatasetProps> = ({
  title,
  bodyA,
  bodyB,
  badgeA,
  badgeB,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();

  const intro = spring({
    frame,
    fps,
    config: {damping: 14, stiffness: 120, mass: 0.9},
  });

  const fade = interpolate(frame, [0, 18], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const textIn = interpolate(frame, [18, 46], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const textY = interpolate(frame, [18, 46], [20, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const floatY = Math.sin(frame / 24) * 6;

  const switchStart = 160;
  const switchMid = 176;
  const switchEnd = 184;

  const bodyAOpacity = interpolate(frame, [18, 32, switchStart, switchMid], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const bodyBOpacity = interpolate(
    frame,
    [switchMid, switchEnd, durationInFrames],
    [0, 1, 1],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    },
  );

  const bodyAY = interpolate(frame, [switchStart, switchMid], [0, -10], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const bodyBY = interpolate(frame, [switchMid, switchEnd], [10, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const badgeAOpacity = interpolate(frame, [0, 18, switchStart, switchMid], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const badgeBOpacity = interpolate(
    frame,
    [switchMid, switchEnd, durationInFrames],
    [0, 1, 1],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    },
  );

  const highlightBase = interpolate(frame, [switchEnd, switchEnd + 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const highlightPulse = 0.35 + 0.25 * Math.sin(frame / 20);
  const highlightStrength = highlightBase * highlightPulse;

  const highlightCells = useMemo(() => new Set([2, 7]), []);

  const glowPulse = interpolate(
    frame,
    [0, durationInFrames * 0.45, durationInFrames * 0.72, durationInFrames],
    [0.72, 1, 0.86, 1],
  );

  const badgeBaseStyle = {
    position: 'absolute' as const,
    right: 18,
    top: 14,
    display: 'inline-flex',
    alignItems: 'center',
    padding: '6px 12px',
    borderRadius: 999,
    border: '1px solid rgba(123, 100, 255, 0.35)',
    background: 'rgba(109, 75, 255, 0.14)',
    fontSize: 16,
    fontWeight: 600,
    letterSpacing: 0.2,
    color: 'rgba(243, 238, 255, 0.9)',
    boxShadow: '0 6px 16px rgba(20, 12, 38, 0.6)',
    minWidth: 180,
    justifyContent: 'center',
    whiteSpace: 'nowrap' as const,
  };

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
          opacity: 0.16,
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
              ...badgeBaseStyle,
              opacity: badgeAOpacity,
            }}
          >
            {badgeA}
          </div>
          <div
            style={{
              ...badgeBaseStyle,
              opacity: badgeBOpacity,
              transform: `translateY(${interpolate(frame, [switchStart, switchEnd], [6, 0], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              })}px)`,
            }}
          >
            {badgeB}
          </div>
          <div
            style={{
              position: 'absolute',
              left: 22,
              right: 22,
              top: 60,
              bottom: 22,
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gridTemplateRows: 'repeat(3, 1fr)',
              gap: 12,
              opacity: interpolate(frame, [18, 36], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              }),
              transform: `scale(${interpolate(frame, [18, 36], [0.96, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              })})`,
              transformOrigin: 'center',
            }}
          >
            {Array.from({length: 12}).map((_, idx) => {
              const isHighlight = highlightCells.has(idx);
              const baseAlpha = 0.1 + (idx % 3) * 0.015;
              const alpha = baseAlpha + (isHighlight ? highlightStrength * 0.22 : 0);
              const shadow = isHighlight ? highlightStrength * 0.55 : 0;
              const topLineWidth = 0.55 + ((idx * 37) % 30) / 100;
              const bottomLineWidth = 0.35 + ((idx * 19) % 40) / 100;
              return (
                <div
                  key={`cell-${idx}`}
                  style={{
                    borderRadius: 10,
                    background: `rgba(243, 238, 255, ${alpha})`,
                    border: '1px solid rgba(120, 96, 255, 0.25)',
                    boxShadow: isHighlight
                      ? `0 0 ${12 + shadow * 18}px rgba(109, 75, 255, ${shadow})`
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
                      width: `${topLineWidth * 100}%`,
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
                      width: `${bottomLineWidth * 100}%`,
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
