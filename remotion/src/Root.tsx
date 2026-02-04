import {Composition} from 'remotion';
import {OnboardingAICoach, OnboardingAICoachProps} from './compositions/OnboardingAICoach';
import {OnboardingCompassWhy, OnboardingCompassWhyProps} from './compositions/OnboardingCompassWhy';
import {OnboardingHowItWorks, OnboardingHowItWorksProps} from './compositions/OnboardingHowItWorks';
import {
  OnboardingPersonalDataset,
  OnboardingPersonalDatasetProps,
} from './compositions/OnboardingPersonalDataset';
import {OnboardingWhyQuit, OnboardingWhyQuitProps} from './compositions/OnboardingWhyQuit';
import {OnboardingWhatIs, OnboardingWhatIsProps} from './compositions/OnboardingWhatIs';

export const Root: React.FC = () => {
  const durationInFrames = 180;
  const longDurationInFrames = 240;
  const aiCoachDurationInFrames = 210;

  return (
    <>
      <Composition
        id="OnboardingWhatIs"
        component={OnboardingWhatIs}
        durationInFrames={durationInFrames}
        fps={30}
        width={1080}
        height={1080}
        defaultProps={
          {
          title: 'Компас',
          subtitle: 'Быстрый трекер привычек + голосовой личный дневник',
          body:
            'Ты фиксируешь день за минуту, а раз в неделю получаешь разбор и инсайты о твоей жизни от ИИ.',
          logoSrc: 'logo.png',
          } satisfies OnboardingWhatIsProps
        }
      />
      <Composition
        id="OnboardingCompassWhy"
        component={OnboardingCompassWhy}
        durationInFrames={durationInFrames}
        fps={30}
        width={1080}
        height={1080}
        defaultProps={
          {
          title: 'Почему “Компас”',
          body:
            'Компас не строит маршрут и не обещает “куда ты придёшь”.\nОн отвечает на главный вопрос: в каком направлении имеет смысл двигаться сегодня — исходя из того, что реально происходит.',
          } satisfies OnboardingCompassWhyProps
        }
      />
      <Composition
        id="OnboardingWhyQuit"
        component={OnboardingWhyQuit}
        durationInFrames={durationInFrames}
        fps={30}
        width={1080}
        height={1080}
        defaultProps={
          {
          title: 'Почему ты бросал',
          body:
            'Большинство трекеров и дневников забрасываются одинаково: вести их долго, муторно, в какой‑то момент скучно.\nКомпас сделан так, чтобы ты не сдался на рутине.',
          logoSrc: 'logo.png',
          } satisfies OnboardingWhyQuitProps
        }
      />
      <Composition
        id="OnboardingHowItWorks"
        component={OnboardingHowItWorks}
        durationInFrames={durationInFrames}
        fps={30}
        width={1080}
        height={1080}
        defaultProps={
          {
          title: 'Как это работает',
          body:
            'Привычки — отмечаются за ~10 секунд.\nЧтобы сделать запись в дневник — просто запиши голосовое: оно сохранится текстом.',
          logoSrc: 'logo.png',
          } satisfies OnboardingHowItWorksProps
        }
      />
      <Composition
        id="OnboardingPersonalDataset"
        component={OnboardingPersonalDataset}
        durationInFrames={longDurationInFrames}
        fps={30}
        width={1080}
        height={1080}
        defaultProps={
          {
          title: 'Личный датасет',
          bodyA:
            'С каждым днём растёт личный датасет:\nчто ты делал, в каком состоянии был,\nчто на тебя влияло.',
          bodyB:
            'Через месяц — “цифровая память”.\nЧерез год — история твоей жизни, которую\nможно анализировать и улучшать.',
          badgeA: 'Датасет',
          badgeB: 'Цифровая память',
          } satisfies OnboardingPersonalDatasetProps
        }
      />
      <Composition
        id="OnboardingAICoach"
        component={OnboardingAICoach}
        durationInFrames={aiCoachDurationInFrames}
        fps={30}
        width={1080}
        height={1080}
        defaultProps={
          {
          title: 'ИИ‑коуч',
          bodyA:
            'Видит паттерны на дистанции:\nгде ты стабилен, а где системно себя сливаешь.',
          bodyB:
            'Со временем он становится точнее —\nпотому что понимает тебя на основе реальных данных.',
          logoSrc: 'logo.png',
          } satisfies OnboardingAICoachProps
        }
      />
    </>
  );
};
