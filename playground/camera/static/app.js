// First experiment: browser-local camera and one JPEG snapshot.
const preview = document.getElementById('preview');
const startButton = document.getElementById('start');
const stopButton = document.getElementById('stop');
const captureButton = document.getElementById('capture');
const statusText = document.getElementById('status');
let stream = null;
let photoUrl = null;
let starting = false;
let capturedPhoto = null;
let captureId = null;
let analyzing = false;
const analyzeButton = document.getElementById('analyze');
const analysisStatus = document.getElementById('analysisStatus');
const eyesButton = document.getElementById('findEyes');

function stopCamera() {
  if (stream) stream.getTracks().forEach(track => track.stop());
  stream = null;
  preview.srcObject = null;
  startButton.disabled = false;
  stopButton.disabled = true;
  captureButton.disabled = true;
  statusText.textContent = 'Camera is off.';
}

startButton.addEventListener('click', async () => {
  if (starting || stream) return;
  if (!navigator.mediaDevices?.getUserMedia) {
    statusText.textContent = 'Camera access is unavailable here. Open http://localhost:5050 in Chrome or Edge.';
    return;
  }
  starting = true;
  startButton.disabled = true;
  statusText.textContent = 'Allow camera access when your browser asks.';
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    preview.srcObject = stream;
    stopButton.disabled = false;
    stream.getVideoTracks()[0].addEventListener('ended', () => {
      stopCamera();
      statusText.textContent = 'Camera disconnected. Reconnect it and press Start camera.';
    });
    await preview.play();
    if (!stream) return; // User may have stopped while video playback was starting.
    captureButton.disabled = analyzing || !preview.videoWidth;
    statusText.textContent = 'Camera is on.';
  } catch (error) {
    stopCamera();
    const messages = {
      NotAllowedError: 'Camera permission was denied. Allow camera access in the browser settings, then try again.',
      NotFoundError: 'No camera found. Connect a USB camera or enable your built-in camera.',
      NotReadableError: 'Camera could not start. Close other apps using it and try again.',
      AbortError: 'Camera startup was interrupted. Try again.'
    };
    statusText.textContent = messages[error.name] || 'Camera could not start. Try Chrome or Edge and check your camera settings.';
  } finally {
    starting = false;
    startButton.disabled = Boolean(stream);
  }
});

preview.addEventListener('loadeddata', () => {
  captureButton.disabled = analyzing || !stream || !preview.videoWidth;
});
stopButton.addEventListener('click', stopCamera);

captureButton.addEventListener('click', () => {
  if (analyzing || !stream || !preview.videoWidth || preview.readyState < 2) return;
  const canvas = document.createElement('canvas');
  canvas.width = preview.videoWidth;
  canvas.height = preview.videoHeight;
  canvas.getContext('2d').drawImage(preview, 0, 0);
  canvas.toBlob(blob => {
    if (!blob) {
      statusText.textContent = 'Could not capture the photo. Try again.';
      return;
    }
    capturedPhoto = blob;
    captureId = crypto.randomUUID();
    analyzeButton.disabled = false;
    eyesButton.disabled = false;
    document.getElementById('annotatedPanel').hidden = true;
    analysisStatus.textContent = '';
    document.getElementById('answerPanel').hidden = true;
    document.getElementById('answer').textContent = '';
    if (photoUrl) URL.revokeObjectURL(photoUrl);
    photoUrl = URL.createObjectURL(blob);
    document.getElementById('photo').src = photoUrl;
    document.getElementById('download').href = photoUrl;
    document.getElementById('result').hidden = false;
    statusText.textContent = `Photo captured (${canvas.width} × ${canvas.height}).`;
  }, 'image/jpeg', 0.9);
});

window.addEventListener('pagehide', () => {
  stopCamera();
  if (photoUrl) URL.revokeObjectURL(photoUrl);
});

async function analyzeCapturedPhoto(mode) {
  if (!capturedPhoto || analyzing) return;
  analyzing = true;
  const sentCaptureId = captureId;
  analyzeButton.disabled = true;
  eyesButton.disabled = true;
  captureButton.disabled = true;
  document.getElementById('prompt').disabled = true;
  document.getElementById('answerPanel').hidden = true;
  document.getElementById('annotatedPanel').hidden = true;
  analysisStatus.textContent = mode === 'eyes' ? 'Locating eyes...' : 'Analyzing captured photo...';
  const form = new FormData();
  form.append('photo', capturedPhoto, 'capture.jpg');
  form.append('capture_id', sentCaptureId);
  form.append('mode', mode);
  form.append('prompt', document.getElementById('prompt').value);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 135000);
  try {
    const response = await fetch('/api/analyze', {method: 'POST', body: form, signal: controller.signal});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Analysis failed.');
    if (data.capture_id !== captureId) return;
    document.getElementById('answer').textContent = data.answer;
    document.getElementById('analysisMeta').textContent = `${data.model} · ${data.elapsed_seconds}s`;
    if (mode === 'eyes') {
      const image = await createImageBitmap(capturedPhoto);
      try {
        drawEyeBoxes(document.getElementById('annotated'), image, data.boxes,
          data.coordinate_width, data.coordinate_height);
      } finally { image.close(); }
      document.getElementById('annotatedPanel').hidden = false;
    }
    document.getElementById('answerPanel').hidden = false;
    analysisStatus.textContent = 'Analysis complete.';
  } catch (error) {
    analysisStatus.textContent = error.name === 'AbortError'
      ? 'Analysis timed out. Try again.'
      : error instanceof TypeError || error instanceof SyntaxError
        ? 'Cannot reach the analysis server. Check the Python terminal and try again.'
        : error.message;
  } finally {
    clearTimeout(timeout);
    analyzing = false;
    analyzeButton.disabled = !capturedPhoto;
    eyesButton.disabled = !capturedPhoto;
    captureButton.disabled = !stream || !preview.videoWidth;
    document.getElementById('prompt').disabled = false;
  }
}

analyzeButton.addEventListener('click', () => analyzeCapturedPhoto('describe'));
eyesButton.addEventListener('click', () => analyzeCapturedPhoto('eyes'));

