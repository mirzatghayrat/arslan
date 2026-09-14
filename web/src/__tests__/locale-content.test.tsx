import { render, screen, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { I18nextProvider } from 'react-i18next';
import { createInstance } from 'i18next';
import DeckDownloadCard from '../components/DeckDownloadCard';
import en from '../locales/en.json';
import de from '../locales/de.json';
import es from '../locales/es.json';
import fr from '../locales/fr.json';
import ja from '../locales/ja.json';
import zh from '../locales/zh.json';

const locales = { en, de, es, fr, ja, zh };
afterEach(cleanup);

describe('product-owned translated copy', () => {
  it.each(Object.entries({ en, de, es, fr }))('%s has no Chinese text', (_, locale) => {
    expect(JSON.stringify(locale)).not.toMatch(/\p{Script=Han}/u);
  });

  it.each(Object.entries(locales))('deck card uses %s copy and preserves filenames', async (lng, locale) => {
    const i18n = createInstance();
    await i18n.init({ lng, resources: { [lng]: { translation: locale } }, interpolation: { escapeValue: false } });
    render(<I18nextProvider i18n={i18n}><DeckDownloadCard filename="用户文件.pptx" bytesB64="" slides={3} /></I18nextProvider>);
    expect(screen.getByRole('button', { name: locale.files.download })).toBeTruthy();
    expect(screen.getByText(`用户文件.pptx · ${locale.activity.deck_slides.replace('{{slides}}', '3')}`)).toBeTruthy();
  });
});
