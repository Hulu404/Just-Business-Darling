/* Тема клиники: { name, logo_url, accent } → --clinic-accent, --clinic-on-accent, --clinic-name, шапка и заголовок вкладки.
   Правило — docs/rescan-pilot/design/theme-system.md. Клиника меняет только логотип, акцент и название.
   Акцент — только #RGB или #RRGGBB; контраст с белым по WCAG без округления: от 4,5 — акцент клиники с белым текстом,
   иначе наш --rs-accent. Подстановка тихая: в консоль не пишем. На <html> — data-accent="clinic" или "fallback".
   Логотип — только с того же источника и из /assets/ (иначе CSP); нет, чужой или не загрузился — название текстом.
   У сотрудника тема клиники не применяется: роутер вызывает reset(). */
import { SHELL } from './texts.js';

export const MIN_CONTRAST = 4.5;
const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;
const VARS = ['--clinic-accent', '--clinic-on-accent', '--clinic-name'];

/* '#abc' → '#AABBCC'; неверная строка → null */
export function normalizeHex(color){
  if (typeof color !== 'string' || !HEX.test(color.trim())) return null;
  const value = color.trim().slice(1);
  const full = value.length === 3 ? value.split('').map(c => c + c).join('') : value;
  return '#' + full.toUpperCase();
}

/* Контраст цвета с белым по WCAG 2.x; для неверной строки — 0 */
export function contrastWithWhite(color){
  const hex = normalizeHex(color);
  if (!hex) return 0;
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 1.05 / (0.2126 * r + 0.7152 * g + 0.0722 * b + 0.05);
}

/* Адрес логотипа, если он с того же источника и из /assets/; иначе null */
export function sameOriginLogo(url){
  if (typeof url !== 'string' || !url.trim()) return null;
  try {
    const parsed = new URL(url.trim(), window.location.href);
    if (parsed.origin !== window.location.origin || !parsed.pathname.startsWith('/assets/')) return null;
    return parsed.pathname + parsed.search;
  } catch {
    return null;
  }
}

const cssString = text => `"${String(text).replace(/[\\"]/g, c => `\\${c}`).replace(/[\r\n]+/g, ' ')}"`;

function renderBrand(name, logo){
  const brand = document.getElementById('brand');
  if (!brand) return;
  brand.replaceChildren();
  if (logo && name){
    const img = document.createElement('img');
    img.className = 'brand-logo';
    img.alt = name;
    img.addEventListener('error', () => renderBrand(name, null), {once:true});
    img.src = logo;
    brand.append(img);
    return;
  }
  if (!name) return;
  const label = document.createElement('span');
  label.className = 'brand-name';
  label.textContent = name;
  brand.append(label);
}

let current = Object.freeze({name:'', logo_url:null, accent:null, accent_replaced:false});

/* Принимает { name, logo_url, accent } или клинику из ответа сессии { name, theme: { logo_url, accent } } */
function apply(input = {}){
  const source = input && typeof input === 'object' ? {...(input.theme || {}), ...input} : {};
  const name = typeof source.name === 'string' ? source.name.trim() : '';
  const accent = normalizeHex(source.accent);
  const accepted = accent !== null && contrastWithWhite(accent) >= MIN_CONTRAST;
  const logo = sameOriginLogo(source.logo_url);
  const root = document.documentElement;
  root.style.setProperty('--clinic-accent', accepted ? accent : 'var(--rs-accent)');
  root.style.setProperty('--clinic-on-accent', accepted ? '#FFFFFF' : 'var(--rs-on-accent)');
  root.style.setProperty('--clinic-name', cssString(name));
  root.dataset.accent = accepted ? 'clinic' : 'fallback';
  renderBrand(name, logo);
  document.title = name ? SHELL.title.replace('{clinic_name}', name) : SHELL.title_fallback;
  current = Object.freeze({name, logo_url:logo, accent:accepted ? accent : null, accent_replaced:!accepted});
  return current;
}

/* Наша тема. brand: текст в шапке ('' — пусто, пока клиника не известна) */
function reset({brand = SHELL.brand} = {}){
  const root = document.documentElement;
  VARS.forEach(name => root.style.removeProperty(name));
  delete root.dataset.accent;
  renderBrand(brand, null);
  document.title = SHELL.title_fallback;
  current = Object.freeze({name:'', logo_url:null, accent:null, accent_replaced:false});
}

export const theme = Object.freeze({apply, reset, current:() => current});
