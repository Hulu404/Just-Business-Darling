import { home, pharmacy } from './pages/patient.js';
import { inbox } from './pages/staff.js';

/* ---------- Иконки ---------- */
export const ICONS = {
  home:'<path d="M3 11l9-7 9 7"/><path d="M5.5 9.5V20h13V9.5"/>',
  route:'<circle cx="6" cy="6" r="2.2"/><circle cx="18" cy="18" r="2.2"/><path d="M8.2 6H15a3 3 0 0 1 0 6H9a3 3 0 0 0 0 6h6.8"/>',
  scan:'<rect x="3" y="3" width="18" height="18" rx="4"/><circle cx="12" cy="12" r="4"/><path d="M12 5.5v2M12 16.5v2M5.5 12h2M16.5 12h2"/>',
  calendar:'<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  message:'<path d="M4 5h16v11H10l-5 4v-4H4z"/>',
  pharmacy:'<rect x="3" y="3" width="18" height="18" rx="5"/><path d="M12 8v8M8 12h8"/>',
  doc:'<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
  inbox:'<path d="M3 13l3-8h12l3 8v6H3z"/><path d="M3 13h5l1 3h6l1-3h5"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  doctor:'<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-4 3-6 6.5-6s5.9 2 6.5 6"/><path d="M18 7v6M15 10h6"/>',
  link:'<path d="M7 8h13M17 5l3 3-3 3M17 16H4M7 13l-3 3 3 3"/>',
  sliders:'<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  bars:'<path d="M5 20V11M12 20V4M19 20v-7"/>',
  map:'<circle cx="5" cy="12" r="2.2"/><circle cx="19" cy="5.5" r="2.2"/><circle cx="19" cy="18.5" r="2.2"/><path d="M7 11l10-4.5M7 13l10 4.5"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  menu:'<path d="M4 7h16M4 12h16M4 17h16"/>',
  check:'<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  cart:'<path d="M3 4h2.5l2.3 11h10.4L20.5 7H7"/><circle cx="9.5" cy="19" r="1.4"/><circle cx="16.5" cy="19" r="1.4"/>',
  spark:'<path d="M12 3v6M12 15v6M3 12h6M15 12h6M6 6l3.5 3.5M14.5 14.5L18 18M18 6l-3.5 3.5M9.5 14.5L6 18"/>',
  after:'<path d="M7 17L17 7M9 7h8v8"/>',
  device:'<rect x="7" y="3" width="10" height="18" rx="3"/><path d="M10 8h4M10 12h4"/>',
  pill:'<g transform="rotate(-40 12 12)"><rect x="3" y="8.5" width="18" height="7" rx="3.5"/><path d="M12 8.5v7"/></g>',
  drop:'<path d="M12 3c4 5 6.5 8 6.5 11.5a6.5 6.5 0 0 1-13 0C5.5 11 8 8 12 3z"/>',
  bandage:'<g transform="rotate(-35 12 12)"><rect x="2.5" y="8.5" width="19" height="7" rx="3.5"/><path d="M9 8.5v7M15 8.5v7"/></g>'
};
export const icon = name => `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;
