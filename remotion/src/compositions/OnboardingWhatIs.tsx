import React, {useMemo} from 'react';
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

export type OnboardingWhatIsProps = {
  title: string;
  subtitle: string;
  body: string;
  logoSrc: string | null;
};

const blinkScale = (frame: number, at: number) => {
  const t = frame - at;
  if (t < 0 || t > 6) {
    return 1;
  }
  return interpolate(t, [0, 2, 4, 6], [1, 0.1, 0.1, 1]);
};

export const OnboardingWhatIs: React.FC<OnboardingWhatIsProps> = ({
  title,
  subtitle,
  body,
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

  const logoSpring = spring({
    frame,
    fps,
    config: {
      damping: 14,
      stiffness: 120,
      mass: 0.9,
    },
  });

  const introFade = interpolate(frame, [0, 20], [0, 1], {
    extrapolateRight: 'clamp',
  });

  const textIn = interpolate(frame, [24, 50], [0, 1], {
    extrapolateRight: 'clamp',
  });

  const textY = interpolate(frame, [24, 50], [28, 0], {
    extrapolateRight: 'clamp',
  });

  const glowPulse = interpolate(
    frame,
    [0, durationInFrames * 0.4, durationInFrames * 0.7, durationInFrames],
    [0.6, 1, 0.8, 1],
  );

  const floatY = Math.sin(frame / 18) * 8;

  const eyeScaleY = Math.min(blinkScale(frame, 96), blinkScale(frame, 132));

  const particles = useMemo(
    () =>
      [
        {x: 140, y: 460, delay: 18},
        {x: 780, y: 520, delay: 42},
        {x: 560, y: 300, delay: 64},
      ],
    [],
  );

  return (
    <AbsoluteFill
      style={{
        background: 'radial-gradient(1200px 1200px at 20% 20%, #14112A 0%, #0B0A17 55%, #070612 100%)',
        color: '#F3EEFF',
        fontFamily: 'Manrope, system-ui, sans-serif',
        padding: '140px 120px',
        justifyContent: 'space-between',
      }}
    >
      <AbsoluteFill style={{opacity: introFade}}>
        <div
          style={{
            position: 'absolute',
            left: '50%',
            top: '35%',
            width: 740,
            height: 740,
            transform: 'translate(-50%, -50%)',
            background: 'radial-gradient(circle, rgba(109,75,255,0.5) 0%, rgba(75,108,255,0.15) 45%, rgba(11,10,23,0) 70%)',
            filter: `blur(${40 * glowPulse}px)`,
            opacity: 0.9,
          }}
        />
      </AbsoluteFill>

      <AbsoluteFill
        style={{
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div
          style={{
            position: 'relative',
            width: 520,
            height: 520,
            transform: `translateY(${-80 + floatY}px) scale(${0.82 + 0.18 * logoSpring})`,
            opacity: introFade,
          }}
        >
          {resolvedLogoSrc ? (
            <img
              src={resolvedLogoSrc}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'contain',
                filter: 'drop-shadow(0 0 40px rgba(109, 75, 255, 0.6))',
              }}
            />
          ) : (
            <>
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  borderRadius: '50%',
                  background:
                    'radial-gradient(70% 70% at 30% 25%, rgba(165, 140, 255, 0.9) 0%, rgba(109, 75, 255, 0.9) 45%, rgba(75, 108, 255, 0.9) 70%, rgba(35, 28, 72, 0.95) 100%)',
                  boxShadow:
                    '0 0 80px rgba(109, 75, 255, 0.7), 0 0 120px rgba(75, 108, 255, 0.35)',
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  right: 60,
                  top: -18,
                  width: 150,
                  height: 150,
                  borderRadius: '50%',
                  background:
                    'radial-gradient(70% 70% at 30% 25%, rgba(196, 173, 255, 0.9) 0%, rgba(118, 89, 255, 0.95) 55%, rgba(59, 64, 126, 0.95) 100%)',
                  filter: 'blur(2px)',
                  transform: 'rotate(-18deg)',
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  left: 140,
                  top: 210,
                  width: 90,
                  height: 120,
                  borderRadius: '50% 50% 45% 45%',
                  background: 'rgba(243, 238, 255, 0.98)',
                  transform: `scaleY(${eyeScaleY})`,
                  transformOrigin: 'center',
                  filter: 'drop-shadow(0 0 12px rgba(255,255,255,0.4))',
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  right: 140,
                  top: 210,
                  width: 90,
                  height: 120,
                  borderRadius: '50% 50% 45% 45%',
                  background: 'rgba(243, 238, 255, 0.98)',
                  transform: `scaleY(${eyeScaleY})`,
                  transformOrigin: 'center',
                  filter: 'drop-shadow(0 0 12px rgba(255,255,255,0.4))',
                }}
              />
            </>
          )}
        </div>
      </AbsoluteFill>

      {particles.map((particle, index) => {
        const pOpacity = interpolate(
          frame,
          [particle.delay, particle.delay + 20, particle.delay + 80],
          [0, 0.8, 0],
          {extrapolateRight: 'clamp'},
        );
        return (
          <div
            key={`particle-${index}`}
            style={{
              position: 'absolute',
              width: 6,
              height: 6,
              borderRadius: '50%',
              left: particle.x,
              top: particle.y,
              background: '#6D4BFF',
              opacity: pOpacity,
              boxShadow: '0 0 14px rgba(109, 75, 255, 0.9)',
            }}
          />
        );
      })}

      <div
        style={{
          position: 'absolute',
          bottom: 110,
          left: 120,
          right: 120,
          opacity: textIn,
          transform: `translateY(${textY}px)`,
        }}
      >
        <div
          style={{
            fontSize: 74,
            fontWeight: 700,
            letterSpacing: 0.4,
            marginBottom: 18,
          }}
        >
          {title}
        </div>
        <div
          style={{
            fontSize: 42,
            fontWeight: 600,
            color: 'rgba(243, 238, 255, 0.88)',
            marginBottom: 22,
          }}
        >
          {subtitle}
        </div>
        <div
          style={{
            fontSize: 34,
            lineHeight: 1.5,
            color: 'rgba(227, 220, 255, 0.8)',
            maxWidth: 840,
          }}
        >
          {body}
        </div>
      </div>
    </AbsoluteFill>
  );
};
