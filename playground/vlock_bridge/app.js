'use strict';
const byId = id => document.getElementById(id);
const text = (tag, value, className = '') => {
  const element = document.createElement(tag);
  element.textContent = value;
  element.className = className;
  return element;
};
const example = {
  asset_id: 'conveyor_01', source_id: 'manual', signal_id: 'person_in_zone',
  kind: 'condition', status: 'active', reason: 'Simulated person in zone',
  ttl_seconds: 30, details: {count: 1}
};
byId('json-input').value = JSON.stringify(example, null, 2);
byId('transport').textContent = location.protocol === 'https:' ? 'Local HTTPS API' : 'Local HTTP API';
let pending = false;
let refreshing = false;
let integrationSettingsLoaded = false;
let applyingIntegrations = false;
let knownAssets = null;
let selectedKind = 'condition';
const signalIds = {condition: 'person_in_zone', measurement: 'people_count'};
const bridgeHeartbeat = new HeartbeatMonitor();

function renderBridgeHealth() {
  const health = bridgeHeartbeat.status(performance.now());
  byId('connection').textContent = health.waiting ? 'Bridge: connecting…' : health.online ? 'Bridge: Online' : 'Bridge: Offline';
  byId('connection').className = 'badge ' + (health.waiting ? '' : health.online ? 'online' : 'offline');
  byId('heartbeat').textContent = health.counter === null ? 'Last heartbeat: waiting'
    : `Last heartbeat: ${health.ageSeconds}s ago`;
  if (!health.waiting && !health.online) {
    byId('output').replaceChildren(text('p', 'Bridge is Offline. Last values must not be treated as current.', 'empty'));
    byId('response').textContent = 'Bridge unavailable or heartbeat stopped. Reconnecting…';
    for (const name of ['mqtt', 'opcua']) {
      byId(name + '-online').textContent = 'Status unavailable';
      byId(name + '-online').className = 'badge offline';
    }
  }
}

function updateSignalHint() {
  const asset = knownAssets?.find(item => item.asset_id === byId('asset').value.trim());
  const signal = asset?.signals.find(item => item.source_id === byId('source').value.trim()
    && item.signal_id === byId('signal').value.trim());
  const mismatch = signal && signal.kind !== byId('kind').value;
  const hint = mismatch
    ? `This Signal ID already belongs to ${signal.kind === 'condition' ? 'an inhibit condition' : 'a measurement'}. Choose another Signal ID for this output type.`
    : signal ? 'Existing signal. Publishing updates this signal; its output type stays fixed.'
    : 'Each signal keeps its output type. Switching type remembers a separate Signal ID.';
  byId('signal-hint').textContent = hint;
  byId('signal-hint').className = mismatch ? 'muted error' : 'muted';
  byId('signal').setCustomValidity(mismatch ? hint : '');
}

async function api(path, body, timeoutMs = 5000) {
  const response = await fetch('/api/v1/' + path, {signal: AbortSignal.timeout(timeoutMs), ...(body === undefined
    ? {cache: 'no-store'}
    : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Bridge request failed.');
  return data;
}

function feedback(message, failed = false) {
  byId('feedback').textContent = message;
  byId('feedback').className = failed ? 'error' : '';
}

function render(state, history) {
  knownAssets = state.assets;
  updateSignalHint();
  byId('response').textContent = JSON.stringify(state, null, 2);
  const output = byId('output');
  output.replaceChildren();
  if (!state.assets.length) output.append(text('p', 'No observations yet. Publish a manual input to create an asset.', 'empty'));
  for (const asset of state.assets) {
    const card = text('article', '', 'asset');
    const heading = text('div', '', 'asset-heading');
    const label = asset.inhibit === null ? 'Unknown' : asset.inhibit ? 'Active' : 'Clear';
    heading.append(text('h3', asset.asset_id), text('span', label, 'badge ' + label.toLowerCase()));
    card.append(heading, text('p', `Inhibit: ${asset.inhibit === null ? 'null' : asset.inhibit} · Quality: ${asset.quality}`));
    for (const signal of asset.signals) {
      const line = text('div', '', 'signal');
      line.append(text('strong', `${signal.source_id} / ${signal.signal_id} · ${signal.status}`));
      if (signal.kind === 'measurement') line.append(text('div', 'Last value: ' + JSON.stringify(signal.value)));
      if (signal.reason || signal.unavailable_reason) line.append(text('div', signal.unavailable_reason
        ? (signal.unavailable_reason === 'restart' ? 'Fresh observation required after restart.' : 'Observation expired.')
        : signal.reason));
      line.append(text('small', `Observed ${new Date(signal.observed_at).toLocaleTimeString()} · expires ${new Date(signal.expires_at).toLocaleTimeString()}`));
      card.append(line);
    }
    output.append(card);
  }
  const rows = history.events.slice().reverse().map(event => {
    const row = document.createElement('tr');
    const data = event.data;
    const value = data.value === undefined || data.value === null ? '' : JSON.stringify(data.value);
    for (const cell of [event.revision, new Date(event.created_at).toLocaleTimeString(), event.asset_id,
      `${data.source_id || ''} / ${data.signal_id || ''}`,
      event.event_type === 'observation' ? data.status : event.event_type,
      [value, data.reason].filter(Boolean).join(' · ')]) row.append(text('td', cell));
    return row;
  });
  byId('events').replaceChildren(...rows);
  byId('history-info').textContent = `Latest 5 · storing up to ${history.retention_limit} events`;
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const state = await api('assets');
    const history = await api('events?limit=5');
    render(state, history);
    bridgeHeartbeat.observe(state, performance.now());
    renderBridgeHealth();
  } catch {
    knownAssets = null;
    updateSignalHint();
    bridgeHeartbeat.unavailable();
    renderBridgeHealth();
    byId('output').replaceChildren(text('p', 'Cannot read bridge state. Last values must not be treated as current.', 'empty'));
    byId('response').textContent = 'Bridge unavailable. Reconnecting…';
  } finally {
    refreshing = false;
  }
}

async function submit(payload) {
  if (pending) return;
  pending = true;
  document.querySelectorAll('#input-form button, #send-json').forEach(button => { button.disabled = true; });
  // Keep an ID for this attempt; never automatically retry an uncertain outcome.
  payload.observation_id ||= crypto.randomUUID();
  try {
    const result = await api('observations', payload);
    feedback(`${result.duplicate ? 'Already recorded' : 'Published'}: ${result.observation.status}. Observation ${result.observation.observation_id}`);
    await refresh();
  } catch (error) {
    feedback(`${error.message} Request ID: ${payload.observation_id}`, true);
  } finally {
    pending = false;
    document.querySelectorAll('#input-form button, #send-json').forEach(button => { button.disabled = false; });
  }
}

byId('kind').addEventListener('change', () => {
  signalIds[selectedKind] = byId('signal').value;
  selectedKind = byId('kind').value;
  byId('signal').value = signalIds[selectedKind];
  const measurement = byId('kind').value === 'measurement';
  byId('value-label').hidden = !measurement;
  byId('active').textContent = measurement ? 'Publish value' : 'Publish active';
  byId('clear').hidden = measurement;
  updateSignalHint();
});
for (const id of ['asset', 'source', 'signal']) byId(id).addEventListener('input', updateSignalHint);
byId('input-form').addEventListener('submit', event => {
  event.preventDefault();
  try {
    const kind = byId('kind').value;
    const pressed = event.submitter?.value || 'active';
    const payload = {
      asset_id: byId('asset').value.trim(), source_id: byId('source').value.trim(),
      signal_id: byId('signal').value.trim(), kind,
      status: kind === 'measurement' && pressed === 'active' ? 'valid' : pressed,
      reason: byId('reason').value, ttl_seconds: Number(byId('ttl').value)
    };
    if (kind === 'measurement' && pressed !== 'unknown') payload.value = JSON.parse(byId('value').value);
    submit(payload);
  } catch { feedback('Value must be valid JSON, for example 12 or {"count":12}.', true); }
});
byId('send-json').addEventListener('click', () => {
  try {
    const payload = JSON.parse(byId('json-input').value);
    if (!payload || Array.isArray(payload) || typeof payload !== 'object') throw new Error();
    payload.observation_id ||= crypto.randomUUID();
    byId('json-input').value = JSON.stringify(payload, null, 2);
    submit(payload);
  } catch { feedback('Enter one valid JSON observation object.', true); }
});
function renderIntegrations(data) {
  if (!integrationSettingsLoaded) {
    for (const name of ['mqtt', 'opcua']) {
      byId(name + '-enabled').checked = data.settings[name].enabled;
      byId(name + '-port').value = data.settings[name].port;
    }
    byId('mqtt-host').value = data.settings.mqtt.host;
    byId('mqtt-prefix').value = data.settings.mqtt.topic_prefix;
    integrationSettingsLoaded = true;
    byId('apply-integrations').disabled = false;
  }
  for (const name of ['mqtt', 'opcua']) {
    const state = data.adapters[name];
    const label = !data.settings[name].enabled ? 'Disabled' : state.online ? 'Online' : 'Offline';
    byId(name + '-online').textContent = label;
    byId(name + '-online').className = 'badge ' + (label === 'Disabled' ? '' : state.online ? 'online' : 'offline');
    byId(name + '-status').textContent = `${state.status}: ${state.message}`;
  }
  byId('opcua-endpoint').textContent = `opc.tcp://127.0.0.1:${data.settings.opcua.port}/vlock/`;
  if (data.settings_error) byId('integration-feedback').textContent = data.settings_error;
}

async function refreshIntegrations() {
  if (applyingIntegrations) return;
  try { renderIntegrations(await api('integrations')); }
  catch {
    for (const name of ['mqtt', 'opcua']) {
      byId(name + '-status').textContent = 'Adapter status unavailable.';
      byId(name + '-online').textContent = 'Status unavailable';
      byId(name + '-online').className = 'badge offline';
    }
  }
}

byId('integration-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (applyingIntegrations) return;
  applyingIntegrations = true;
  byId('apply-integrations').disabled = true;
  byId('integration-feedback').textContent = 'Applying settings…';
  const settings = {
    mqtt: {enabled: byId('mqtt-enabled').checked, host: byId('mqtt-host').value,
      port: Number(byId('mqtt-port').value), topic_prefix: byId('mqtt-prefix').value.trim()},
    opcua: {enabled: byId('opcua-enabled').checked, port: Number(byId('opcua-port').value)}
  };
  try {
    const data = await api('integrations', settings, 20000);
    renderIntegrations(data);
    byId('integration-feedback').textContent = 'Settings saved. Check adapter status for connection confirmation.';
  } catch (error) { byId('integration-feedback').textContent = error.message + ' Re-read status before retrying.'; }
  finally { applyingIntegrations = false; byId('apply-integrations').disabled = !integrationSettingsLoaded; }
});
updateSignalHint();
renderBridgeHealth();
setInterval(renderBridgeHealth, 250);
refresh().finally(() => { setInterval(refresh, 1000); });
refreshIntegrations().finally(() => { setInterval(refreshIntegrations, 2000); });
