// Live camera frames remain original JPEGs. This layer only draws UI geometry.
function illustration(config, editable=false, drawing=false, drawingPoints=[]) {
  const size=config.runtime?.camera?.frame_size||[640,480];
  const [w,h]=size;
  const points=(drawing?drawingPoints:config.zone).map(p=>`${p[0]*w},${p[1]*h}`).join(' ');
  const connected=config.connected;
  return `<div class="scene-wrap live-camera"><svg class="scene ${config.showArea===false&&!drawing?'area-hidden':''}" id="scene" viewBox="0 0 ${w} ${h}" role="img" aria-label="Camera preview${editable?' and area editor':''}">
    <rect width="${w}" height="${h}" fill="#203c37"/>
    ${connected?`<image class="camera-frame" data-zone="${escapeHtml(config.id)}" width="${w}" height="${h}" preserveAspectRatio="none"/>`:`<text x="50%" y="50%" fill="#b1c5b5" text-anchor="middle" font-size="14">Connect the camera to see its view</text>`}
    ${config.areaSelected||drawing?`<polygon class="zone" points="${points}"/>`:''}
    ${editable&&!drawing&&config.areaSelected?config.zone.map((p,i)=>`<circle class="zone-handle" data-point="${i}" cx="${p[0]*w}" cy="${p[1]*h}" r="5" tabindex="0" role="button" aria-label="Zone vertex ${i+1}; use arrow keys to move"/>`).join(''):''}
    ${drawing?drawingPoints.map(p=>`<circle cx="${p[0]*w}" cy="${p[1]*h}" r="4" fill="#d8f9d9"/>`).join(''):''}
  </svg><span class="frame-state">${connected?'Camera preview · waiting for frame':'Not connected'}</span></div>`;
}
