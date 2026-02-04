import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {loadFont} from '@remotion/google-fonts/Manrope';
import {Icon} from '@iconify/react';

loadFont();

export type OnboardingCompassWhyProps = {
  title: string;
  body: string;
};

export const OnboardingCompassWhy: React.FC<OnboardingCompassWhyProps> = ({
  title,
  body,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();

  const intro = spring({
    frame,
    fps,
    config: {damping: 14, stiffness: 110, mass: 0.9},
  });

  const fade = interpolate(frame, [0, 18], [0, 1], {
    extrapolateRight: 'clamp',
  });

  const textIn = interpolate(frame, [18, 46], [0, 1], {
    extrapolateRight: 'clamp',
  });

  const textY = interpolate(frame, [18, 46], [20, 0], {
    extrapolateRight: 'clamp',
  });

  const needleAngle = interpolate(
    frame,
    [0, durationInFrames * 0.35, durationInFrames * 0.7, durationInFrames],
    [-18, 8, -6, 2],
  );

  const gridShift = interpolate(frame, [0, durationInFrames], [0, 60]);
  const glow = interpolate(frame, [0, durationInFrames], [0.7, 1]);

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
            'linear-gradient(rgba(114, 92, 255, 0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(114, 92, 255, 0.08) 1px, transparent 1px)',
          backgroundSize: '80px 80px',
          transform: `translate(${gridShift}px, ${gridShift}px)`,
          opacity: 0.4,
        }}
      />

      <div
        style={{
          position: 'absolute',
          left: '50%',
          top: '34%',
          width: 480,
          height: 480,
          transform: `translate(-50%, -50%) scale(${0.85 + 0.15 * intro})`,
          opacity: fade,
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 0,
            borderRadius: '50%',
            background:
              'radial-gradient(circle, rgba(111, 78, 255, 0.35) 0%, rgba(64, 86, 203, 0.15) 55%, rgba(11, 10, 23, 0) 75%)',
            filter: `blur(${32 * glow}px)`,
          }}
        />
        <div
          style={{
            position: 'absolute',
            inset: 40,
            borderRadius: '50%',
            border: '2px solid rgba(126, 104, 255, 0.45)',
            boxShadow: '0 0 20px rgba(111, 78, 255, 0.35)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            inset: 100,
            borderRadius: '50%',
            border: '1px dashed rgba(126, 104, 255, 0.25)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: '50%',
            top: '50%',
            width: 22,
            height: 22,
            borderRadius: '50%',
            background: '#F3EEFF',
            transform: 'translate(-50%, -50%)',
            boxShadow: '0 0 18px rgba(243, 238, 255, 0.7)',
          }}
        />

        <div
          style={{
            position: 'absolute',
            left: '50%',
            top: '50%',
            width: 12,
            height: 210,
            transform: `translate(-50%, -88%) rotate(${needleAngle}deg)`,
            transformOrigin: 'bottom center',
            borderRadius: '8px',
            background:
              'linear-gradient(180deg, rgba(243,238,255,0.95) 0%, rgba(111, 78, 255, 0.85) 100%)',
            boxShadow: '0 0 20px rgba(111, 78, 255, 0.65)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: '50%',
            top: '50%',
            width: 6,
            height: 140,
            transform: `translate(-50%, -85%) rotate(${needleAngle + 180}deg)`,
            transformOrigin: 'bottom center',
            borderRadius: '8px',
            background:
              'linear-gradient(180deg, rgba(85, 110, 255, 0.9) 0%, rgba(47, 38, 96, 0.95) 100%)',
            opacity: 0.7,
          }}
        />

        <div
          style={{
            position: 'absolute',
            left: '50%',
            top: '50%',
            transform: 'translate(-50%, -50%)',
            display: 'flex',
            gap: 12,
          }}
        >
          <Icon icon="mdi:compass-outline" width={54} color="rgba(243, 238, 255, 0.8)" />
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
        <div
          style={{
            fontSize: 34,
            lineHeight: 1.5,
            color: 'rgba(227, 220, 255, 0.85)',
            maxWidth: 860,
            whiteSpace: 'pre-line',
          }}
        >
          {body}
        </div>
      </div>
    </AbsoluteFill>
  );
};
