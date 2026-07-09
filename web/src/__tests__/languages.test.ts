import { test, expect } from 'vitest'
import { LANGUAGE_OPTIONS, normalizeLanguage } from '../lib/languages'

test('exposes all 6 supported languages with native labels', () => {
  expect(LANGUAGE_OPTIONS.map(o => o.code)).toEqual(['en','zh','ja','es','de','fr'])
  expect(LANGUAGE_OPTIONS.find(o => o.code === 'zh')!.label).toBe('简体中文')
})
test('maps legacy label values to codes', () => {
  expect(normalizeLanguage('English (US)')).toBe('en')
  expect(normalizeLanguage('Chinese (Simplified)')).toBe('zh')
  expect(normalizeLanguage('Japanese')).toBe('ja')
  expect(normalizeLanguage('German')).toBe('de')
  expect(normalizeLanguage('de')).toBe('de')
  expect(normalizeLanguage('xx')).toBe('en')
  expect(normalizeLanguage(undefined)).toBe('en')
})
