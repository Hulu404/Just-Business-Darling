/* Точка входа пилота rescan: плашка «демо», тема по умолчанию, роутер. Страница — /assets/pilot/index.html */
import { MODE } from './api.js';
import { start } from './router.js';
import { theme } from './theme.js';
import { SHELL } from './texts.js';

function setupShell(){
  const badge = document.getElementById('demo-badge');
  if (badge){
    badge.hidden = MODE !== 'mock';
    const visible = document.createElement('span');
    visible.setAttribute('aria-hidden', 'true');
    visible.textContent = SHELL.demo_badge;
    const spoken = document.createElement('span');
    spoken.className = 'sr-only';
    spoken.textContent = SHELL.demo_badge_label;
    badge.replaceChildren(visible, spoken);
    badge.title = SHELL.demo_badge_label;
  }
  const footer = document.getElementById('footer');
  if (footer) footer.textContent = SHELL.footer;
}

setupShell();
theme.reset();
start();
