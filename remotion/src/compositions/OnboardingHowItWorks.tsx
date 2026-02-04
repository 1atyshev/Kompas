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
import {Icon} from '@iconify/react';

loadFont();

export type OnboardingHowItWorksProps = {
  title: string;
  body: string;
  logoSrc: string | null;
};

export const OnboardingHowItWorks: React.FC<OnboardingHowItWorksProps> = ({
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

  const checklistStart = 30;
  const checklistEnd = 90;
  const micAppear = 96;
  const micTap = 110;
  const recordStart = 116;
  const recordEnd = 144;
  const sendStart = 150;
  const transcriptStart = 162;

  const checklistOpacity = interpolate(frame, [checklistStart, checklistEnd - 6], [1, 0.35], {
    extrapolateRight: 'clamp',
  });
  const checklistFadeOut = interpolate(frame, [checklistEnd - 6, checklistEnd + 8], [1, 0], {
    extrapolateRight: 'clamp',
  });
  const finalOpacity = interpolate(frame, [transcriptStart, transcriptStart + 10], [0, 1], {
    extrapolateRight: 'clamp',
  });

  const micIn = interpolate(frame, [micAppear, micAppear + 8], [0, 1], {
    extrapolateRight: 'clamp',
  });
  const tapPulse = spring({
    frame: Math.max(0, frame - micTap),
    fps,
    config: {damping: 12, stiffness: 180, mass: 0.7},
  });
  const recordPulse = interpolate(frame, [recordStart, recordEnd], [0, 1], {
    extrapolateRight: 'clamp',
  });
  const sendOpacity = interpolate(frame, [sendStart, sendStart + 10], [0, 1], {
    extrapolateRight: 'clamp',
  });
  const micOpacity = interpolate(frame, [sendStart, sendStart + 10], [1, 0], {
    extrapolateRight: 'clamp',
  });
  const bubbleProgress = interpolate(frame, [sendStart, sendStart + 16], [0, 1], {
    extrapolateRight: 'clamp',
  });

  const loop = frame % 150;
  const yawn = interpolate(loop, [40, 56, 74], [0, 0.06, 0], {
    extrapolateRight: 'clamp',
  });
  const floatY = Math.sin(frame / 18) * 4;

  const resolvedLogoSrc =
    logoSrc && (logoSrc.startsWith('http') || logoSrc.startsWith('data:') || logoSrc.startsWith('/'))
      ? logoSrc
      : logoSrc
        ? staticFile(logoSrc)
        : null;

  const checkPulse = (delay: number) =>
    spring({
      frame: Math.max(0, frame - delay),
      fps,
      config: {damping: 12, stiffness: 180, mass: 0.7},
    });

  const timerPulse = spring({
    frame: Math.max(0, frame - (checklistStart + 8)),
    fps,
    config: {damping: 14, stiffness: 140, mass: 0.8},
  });


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
            filter: 'blur(28px)',
            opacity: 0.7,
          }}
        />

        {resolvedLogoSrc ? (
          <img
            src={resolvedLogoSrc}
            style={{
              position: 'absolute',
              left: '50%',
              top: 212,
              width: 170,
              height: 170,
              objectFit: 'contain',
              transform: `translate(-50%, -50%) translateY(${floatY}px) scaleX(${1 + yawn * 0.15}) scaleY(${1 - yawn})`,
              filter: 'drop-shadow(0 0 22px rgba(109, 75, 255, 0.6))',
              opacity: 1,
            }}
          />
        ) : null}

        <div
          style={{
            position: 'absolute',
            left: '50%',
            top: 300,
            width: 460,
            height: 190,
            transform: 'translateX(-50%)',
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
            }}
          />

          <div
            style={{
              position: 'absolute',
              left: 22,
              top: 22,
              right: 22,
              height: 14,
              borderRadius: 10,
              background: 'rgba(243, 238, 255, 0.12)',
              opacity: checklistFadeOut,
            }}
          />

          <div
            style={{
              position: 'absolute',
              left: 22,
              top: 46,
              right: 22,
              height: 104,
              opacity: checklistOpacity * checklistFadeOut,
            }}
          >
            {[0, 1, 2].map((idx) => {
              const rowY = idx * 28;
              const check = checkPulse(checklistStart + idx * 8);
              return (
                <div key={`row-${idx}`} style={{position: 'absolute', left: 0, right: 0, top: rowY}}>
                  <div
                    style={{
                      position: 'absolute',
                      left: 0,
                      top: 0,
                      width: 18,
                      height: 18,
                      borderRadius: 5,
                      border: '1px solid rgba(243, 238, 255, 0.4)',
                      background: 'rgba(243, 238, 255, 0.05)',
                    }}
                  />
                  <div
                    style={{
                      position: 'absolute',
                      left: 0,
                      top: 0,
                      width: 18,
                      height: 18,
                      borderRadius: 5,
                      background: 'rgba(243, 238, 255, 0.9)',
                      opacity: check,
                      transform: `scale(${0.7 + check * 0.3})`,
                      boxShadow: '0 0 12px rgba(109, 75, 255, 0.6)',
                    }}
                  />
                  <div
                    style={{
                      position: 'absolute',
                      left: 30,
                      top: 3,
                      right: 0,
                      height: 10,
                      borderRadius: 8,
                      background: 'rgba(243, 238, 255, 0.22)',
                    }}
                  />
                </div>
              );
            })}
          </div>

          <div
            style={{
              position: 'absolute',
              right: 22,
              top: 16,
              padding: '4px 8px',
              borderRadius: 10,
              background: 'rgba(109, 75, 255, 0.2)',
              color: 'rgba(243, 238, 255, 0.8)',
              fontSize: 14,
              letterSpacing: 1,
              opacity: checklistOpacity * checklistFadeOut,
              transform: `scale(${0.9 + timerPulse * 0.1})`,
            }}
          >
            ~10s
          </div>

          <div
            style={{
              position: 'absolute',
              left: 22,
              top: 46,
              right: 22,
              height: 104,
              opacity: finalOpacity,
            }}
          >
            {[0, 1, 2].map((idx) => (
              <div
                key={`final-${idx}`}
                style={{
                  position: 'absolute',
                  left: 22,
                  right: idx === 0 ? 120 : idx === 1 ? 160 : 220,
                  top: idx * 22 + 6,
                  height: 9,
                  borderRadius: 8,
                  background: 'rgba(243, 238, 255, 0.75)',
                  boxShadow: '0 0 16px rgba(109, 75, 255, 0.4)',
                }}
              />
            ))}
          </div>

          <div
            style={{
              position: 'absolute',
              right: 14,
              bottom: 14,
              width: 56,
              height: 56,
              borderRadius: '50%',
              background: 'rgba(109, 75, 255, 0.22)',
              border: '1px solid rgba(109, 75, 255, 0.45)',
              boxShadow: '0 0 22px rgba(109, 75, 255, 0.45)',
              transform: `scale(${0.92 + micIn * 0.08 + tapPulse * 0.08})`,
              opacity: micIn,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Icon
              icon="mdi:microphone"
              width={26}
              color="rgba(243, 238, 255, 0.9)"
              style={{opacity: micOpacity}}
            />
            <Icon
              icon="mdi:send"
              width={26}
              color="rgba(243, 238, 255, 0.9)"
              style={{opacity: sendOpacity, position: 'absolute'}}
            />
            <div
              style={{
                position: 'absolute',
                inset: -5,
                borderRadius: '50%',
                border: '1px solid rgba(109, 75, 255, 0.5)',
                opacity: recordPulse * micOpacity,
                transform: `scale(${1 + recordPulse * 0.15})`,
              }}
            />
          </div>

          <div
            style={{
              position: 'absolute',
              right: 34 + bubbleProgress * 140,
              bottom: 34 + bubbleProgress * 48,
              width: 22,
              height: 16,
              borderRadius: 10,
              background: 'rgba(243, 238, 255, 0.7)',
              opacity: sendOpacity * (1 - bubbleProgress),
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
