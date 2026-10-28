// Draw on a separate canvas. Coordinates refer to the exact image sent to Claude.
function drawEyeBoxes(canvas, image, boxes, coordinateWidth, coordinateHeight) {
  canvas.width = image.width;
  canvas.height = image.height;
  const context = canvas.getContext('2d');
  context.drawImage(image, 0, 0);
  const sx = canvas.width / coordinateWidth;
  const sy = canvas.height / coordinateHeight;
  context.strokeStyle = '#00ff72';
  context.lineWidth = Math.max(2, canvas.width / 250);
  for (const box of boxes) {
    const cx = (box.x1 + box.x2) * sx / 2;
    const cy = (box.y1 + box.y2) * sy / 2;
    const side = Math.min(canvas.width, canvas.height,
      Math.max((box.x2 - box.x1) * sx, (box.y2 - box.y1) * sy) * 1.2);
    const x = Math.max(0, Math.min(canvas.width - side, cx - side / 2));
    const y = Math.max(0, Math.min(canvas.height - side, cy - side / 2));
    context.strokeRect(x, y, side, side);
  }
}
