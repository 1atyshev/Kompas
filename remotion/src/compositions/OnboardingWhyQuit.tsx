import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {loadFont} from '@remotion/google-fonts/Manrope';

loadFont();

export type OnboardingWhyQuitProps = {
  title: string;
  body: string;
  logoSrc: string | null;
};

export const OnboardingWhyQuit: React.FC<OnboardingWhyQuitProps> = ({
  title,
  body,
  logoSrc,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const intro = spring({
    frame,
    fps,
    config: {damping: 14, stiffness: 120, mass: 0.9},
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

  const loop = frame % 150;
  const yawn = interpolate(loop, [40, 56, 74], [0, 0.08, 0], {
    extrapolateRight: 'clamp',
  });

  const switchFrame = 128;
  const collapse = spring({
    frame: Math.max(0, frame - switchFrame),
    fps,
    config: {damping: 12, stiffness: 160, mass: 0.7},
  });
  const listOpacity = interpolate(frame, [switchFrame - 8, switchFrame + 10], [1, 0], {
    extrapolateRight: 'clamp',
  });
  const simpleOpacity = interpolate(frame, [switchFrame - 4, switchFrame + 12], [0, 1], {
    extrapolateRight: 'clamp',
  });
  const fatigue = interpolate(frame, [30, switchFrame - 12], [1, 0.45], {
    extrapolateRight: 'clamp',
  });
  const lineGap = interpolate(frame, [30, switchFrame - 12], [18, 12], {
    extrapolateRight: 'clamp',
  });
  const listCount = Math.max(0, Math.min(10, Math.floor((frame - 18) / 6)));

  const resolvedLogoSrc =
    logoSrc && (logoSrc.startsWith('http') || logoSrc.startsWith('data:') || logoSrc.startsWith('/'))
      ? logoSrc
      : logoSrc
        ? staticFile(logoSrc)
        : null;

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
          left: '50%',
          top: '34%',
          width: 520,
          height: 520,
          transform: `translate(-50%, -50%) scale(${0.88 + 0.12 * intro})`,
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
            filter: 'blur(28px)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: '50%',
            top: '42%',
            width: 200,
            height: 200,
            transform: `translate(-50%, -50%) scaleY(${1 - yawn}) scaleX(${1 + yawn * 0.2})`,
            filter: 'drop-shadow(0 0 30px rgba(109, 75, 255, 0.6))',
          }}
        >
          {resolvedLogoSrc ? (
            <img
              src={resolvedLogoSrc}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'contain',
              }}
            />
          ) : null}
        </div>

        <div
          style={{
            position: 'absolute',
            left: '50%',
            top: 300,
            width: 420,
            height: 170,
            transform: `translateX(-50%) scaleY(${1 - collapse * 0.45})`,
            transformOrigin: 'center',
            borderRadius: 20,
            background: 'rgba(15, 12, 32, 0.9)',
            border: '1px solid rgba(123, 100, 255, 0.25)',
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
              left: 22,
              top: 44,
              right: 22,
              height: 96,
              opacity: listOpacity,
              overflow: 'hidden',
            }}
          >
            {Array.from({length: listCount}).map((_, idx) => {
              const lineOpacity = (1 - idx * 0.06) * fatigue;
              return (
                <div
                  key={`line-${idx}`}
                  style={{
                    position: 'absolute',
                    left: 0,
                    right: 0,
                    top: idx * lineGap,
                    height: 9,
                    borderRadius: 8,
                    background: 'rgba(243, 238, 255, 0.22)',
                    opacity: lineOpacity,
                  }}
                />
              );
            })}
          </div>

          <div
            style={{
              position: 'absolute',
              left: 24,
              right: 24,
              top: 58,
              height: 64,
              opacity: simpleOpacity,
              transform: `scale(${1 - collapse * 0.08})`,
            }}
          >
            {[0, 1].map((idx) => (
              <div
                key={`simple-${idx}`}
                style={{
                  position: 'absolute',
                  left: 0,
                  right: idx === 0 ? 60 : 100,
                  top: idx * 24,
                  height: 10,
                  borderRadius: 8,
                  background: 'rgba(243, 238, 255, 0.75)',
                  boxShadow: '0 0 18px rgba(109, 75, 255, 0.5)',
                }}
              />
            ))}
          </div>
          <div
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              top: 0,
              height: 16,
              background:
                'linear-gradient(180deg, rgba(11, 10, 23, 1) 0%, rgba(11, 10, 23, 0) 100%)',
              opacity: listOpacity,
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: 0,
              height: 20,
              background:
                'linear-gradient(0deg, rgba(11, 10, 23, 1) 0%, rgba(11, 10, 23, 0) 100%)',
              opacity: listOpacity,
            }}
          />
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
