// Original illustrated preview. No camera frames or model results.
function illustration(config, editable = false, drawing = false, drawingPoints = [], showPerson = true) {
  const active = true;
  const visiblePerson = showPerson;
  const points = (drawing ? drawingPoints : config.zone).map(p => `${p[0]*800},${p[1]*450}`).join(' ');
  return `<div class="scene-wrap"><span class="scene-title">${escapeHtml(config.cameraName)} · ILLUSTRATED PREVIEW</span><span class="scene-state">${pill('SAMPLE SCENE','outline')}</span>
  <svg class="scene" id="scene" viewBox="0 0 800 450" role="img" aria-label="Illustrated conveyor workspace${editable ? ', drag zone vertices to edit' : ''}">
    <defs><linearGradient id="floor" x1="0" y1="0" x2="0.7" y2="1"><stop stop-color="#bac7c3"/><stop offset="1" stop-color="#7e9690"/></linearGradient><linearGradient id="wall" x2="0" y2="1"><stop stop-color="#d5dfdb"/><stop offset="1" stop-color="#afbeb7"/></linearGradient><linearGradient id="belt" x2="1" y2="1"><stop stop-color="#647f79"/><stop offset="1" stop-color="#344f4a"/></linearGradient><pattern id="floorGrid" width="80" height="80" patternUnits="userSpaceOnUse" patternTransform="skewX(-25) rotate(12)"><path d="M80 0H0V80" fill="none" stroke="#d5e1d6" stroke-opacity=".17"/></pattern><pattern id="rollers" width="15" height="15" patternUnits="userSpaceOnUse" patternTransform="rotate(-18)"><path d="M0 0v15" stroke="#93aaa1" stroke-width="5"/></pattern></defs>
    <rect width="800" height="450" fill="url(#floor)"/><path d="M0 0H800V130L0 205Z" fill="url(#wall)"/><path d="M0 192L800 119v13L0 207Z" fill="#7f9990"/><rect y="165" width="800" height="285" fill="url(#floorGrid)"/>
    <path d="M42 0v186M270 0v163M538 0v141M771 0v120" stroke="#9bae9f" stroke-width="9"/>
    <path d="M73 32l153-11v75L73 109zM309 13L492 0v69L309 85zM573 0h161v46L573 61z" fill="#b8d1c7" stroke="#e4ebe0" stroke-width="5"/><path d="M143 26v77M388 0v78M648 0v55" stroke="#dce8df" stroke-width="4"/>
    <path d="M570 131l151-17 14 142-151 26z" fill="#5c7970"/><path d="M579 139l131-15 2 34-130 16zM583 188l133-17 3 34-132 20zM588 237l133-19 3 30-133 20z" fill="#91a494"/>
    <path d="M598 139l37-5 4 31-38 5zM649 132l45-5 3 30-44 6zM597 191l46-6 4 31-46 7zM659 183l44-6 4 30-44 8zM607 239l35-6 4 27-35 7z" fill="#c0b391"/>
    <path d="M73 267l338-94 251 122-367 121z" fill="#526e65" opacity=".24"/>
    <path d="M117 254l279-78 245 106-307 99z" fill="#96aba0" stroke="#506d61" stroke-width="2"/>
    <path d="M130 252l265-70 227 98-289 92z" fill="url(#belt)"/><path d="M135 252l260-69 222 96-284 91z" fill="url(#rollers)" opacity=".65"/>
    <path d="M117 254v22l217 110 307-99v-5l-307 99z" fill="#4d695d"/><path d="M117 276l217 110v-12L117 267z" fill="#a3b5a5"/>
    <path d="M157 283v61l13 6v-60M331 382v44l14-5v-43M588 308v64l12-5v-63" stroke="#57776a" stroke-width="9"/>
    <path d="M253 221l48-14 43 18-49 15z" fill="#cfc09d"/><path d="M253 221v32l42 20v-33z" fill="#ae9f7b"/><path d="M295 240l49-15v31l-49 17z" fill="#b7ab8b"/><path d="M276 215l43 19v12" stroke="#e0d6bc" stroke-width="6"/>
    <path d="M393 247l51-15 46 20-54 17z" fill="#ccbe9b"/><path d="M393 247v31l43 21v-30z" fill="#a99b78"/><path d="M436 269l54-17v31l-54 16z" fill="#bdaf88"/>
    <path d="M31 331l94-28M422 435l205-67M80 360l24-7M115 350l24-8" stroke="#dfd3a0" stroke-width="5" stroke-dasharray="17 10" opacity=".8"/>
    <polygon class="zone" points="${points}"/>${!drawing ? `<text x="${config.zone[0][0]*800+10}" y="${config.zone[0][1]*450-12}" fill="#e7fff2" font-size="10" font-family="Segoe UI,Arial">${escapeHtml(config.zoneName)}</text>` : ''}
    ${visiblePerson ? `<g transform="translate(${active ? '450 225' : '170 204'})"><ellipse cx="0" cy="94" rx="20" ry="7" fill="#345e4e" opacity=".3"/><circle cy="8" r="11" fill="#d5b99d"/><path d="M-10 22l20 0 7 36-17 8-17-8z" fill="#d0d9a9"/><path d="M-8 28l-3 25M8 28l6 22" stroke="#a9bb7f" stroke-width="7" stroke-linecap="round"/><path d="M-7 61l-4 30M6 61l7 30" stroke="#45675c" stroke-width="9"/><path d="M-17 94h11M9 94h11" stroke="#314e45" stroke-width="6"/><rect x="-28" y="-10" width="56" height="115" rx="3" fill="none" stroke="#deecd9" stroke-width="1.5" stroke-dasharray="4 4"/><rect x="-28" y="-24" width="49" height="13" rx="2" fill="#d9ead1"/><text x="-23" y="-15" fill="#47684b" font-size="8">person · sample</text></g>` : ''}
    ${editable && !drawing ? config.zone.map((p,i) => `<circle class="zone-handle" data-point="${i}" cx="${p[0]*800}" cy="${p[1]*450}" r="5" tabindex="0" role="button" aria-label="Zone vertex ${i+1}; use arrow keys to move"/>`).join('') : ''}
    ${drawing ? drawingPoints.map(p => `<circle cx="${p[0]*800}" cy="${p[1]*450}" r="4" fill="#e7ffed"/>`).join('') : ''}
  </svg><span class="scene-bottom">SYNTHETIC SCENE · NO CAMERA FEED</span></div>`;
}
