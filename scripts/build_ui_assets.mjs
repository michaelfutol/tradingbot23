// Build native bitmap variants from the brand SVG and installed Lucide icons.
import { createRequire } from 'node:module';
import { readFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

const require = createRequire(import.meta.url);
const sharp = require(process.env.SHARP_MODULE || 'sharp');
const icons = require('../web/node_modules/lucide-react');
const out = resolve('assets/ui');
await mkdir(out, { recursive: true });
const mark = await readFile('assets/trade23-mark.svg');
for (const size of [32, 40, 64, 256]) {
  await sharp(mark).resize(size, size).png().toFile(`${out}/mark-${size}.png`);
}
await sharp(mark).resize(256, 256).png().toFile('assets/tradingbot23.png');
const names = { play: 'Play', pause: 'Pause', refresh: 'RefreshCw', send: 'Send',
  download: 'Download', save: 'Check', reset: 'RotateCcw', shield: 'Shield',
  chart: 'ChartNoAxesCombined', close: 'X', settings: 'Settings' };
for (const [name, component] of Object.entries(names)) {
  const nodes = icons[component].render({}, null).props.iconNode;
  const content = nodes.map(([tag, attrs]) => `<${tag} ${Object.entries(attrs)
    .filter(([key]) => key !== 'key').map(([key, value]) => `${key}="${value}"`).join(' ')}/>`).join('');
  for (const [variant, color] of [['light', '#edf1f4'], ['dark', '#111214']]) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${content}</svg>`;
    await sharp(Buffer.from(svg)).png().toFile(`${out}/${name}-${variant}.png`);
  }
}
console.log('Brand and Lucide desktop assets built.');
