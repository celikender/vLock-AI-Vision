"""Build the three-card native Perspective demo; only P1S-01 has live bindings."""
import base64
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

HERE = Path(__file__).resolve().parent
PROJECT = HERE / 'project'
OUT = HERE / 'output'
ROOT = '[default]BambuP1S/'
INK = '#243448'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def tag(path):
    return '{' + ROOT + path + '}'


FRESH = ('(!isNull(' + tag('Connection/LastPoll') + ') && secondsBetween(' +
         tag('Connection/LastPoll') + ', now(1000)) >= 0 && secondsBetween(' +
         tag('Connection/LastPoll') + ', now(1000)) < 6)')
ONLINE = '(' + FRESH + ' && ' + tag('Readings/Online') + ')'


def bind(node, prop, expression):
    node.setdefault('propConfig', {})[prop] = {
        'binding': {'type': 'expr', 'config': {'expression': expression}}}
    return node


def label(name, text, expression=None, size=15, height=28):
    node = {'type': 'ia.display.label', 'meta': {'name': name},
            'position': {'basis': str(height) + 'px', 'grow': 0, 'shrink': 0},
            'props': {'text': text, 'style': {'fontSize': str(size) + 'px',
                      'whiteSpace': 'normal', 'color': INK, 'overflow': 'hidden'}}}
    if expression:
        bind(node, 'props.text', expression)
    return node


def flex(name, children, direction='column', style=None, basis='auto', grow=0, wrap=None):
    return {'type': 'ia.container.flex', 'meta': {'name': name},
            'position': {'basis': basis, 'grow': grow, 'shrink': 0},
            'props': {'direction': direction, 'wrap': wrap or ('wrap' if direction == 'row' else 'nowrap'),
                      'justify': 'flex-start', 'alignItems': 'stretch',
                      'style': dict({'boxSizing': 'border-box', 'gap': '8px', 'minWidth': '0'}, **(style or {}))},
            'children': children}


def button(name, text, call=None, enabled=None, color='#ffffff'):
    node = {'type': 'ia.input.button', 'meta': {'name': name},
            'position': {'basis': '88px', 'grow': 1, 'shrink': 0},
            'props': {'text': text, 'enabled': False, 'primary': False,
                      'style': {'backgroundColor': color, 'color': INK,
                                'border': '1px solid #c6d0da', 'borderRadius': '5px',
                                'height': '36px', 'fontSize': '13px', 'fontWeight': '600'}}}
    if call:
        node['props']['enabled'] = enabled is None
        node['events'] = {'component': {'onActionPerformed': {'type': 'script', 'scope': 'G',
            'config': {'script': '\ttry:\n\t    ' + call + '\n\t    self.view.custom.feedback = ""\n\texcept Exception as exc:\n\t    self.view.custom.feedback = str(exc)'}}}}
    if enabled:
        bind(node, 'props.enabled', enabled)
    return node


def schematic():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="220" viewBox="0 0 200 220">'
           '<rect x="23" y="12" width="154" height="184" rx="7" fill="#edf2f6" stroke="#45566a" stroke-width="4"/>'
           '<rect x="36" y="32" width="128" height="139" fill="white" stroke="#aebcc9" stroke-width="2"/>'
           '<path d="M42 58H158 M100 58V91 M93 91H107L100 103Z M43 148H157 M52 155H148" fill="none" stroke="#45566a" stroke-width="4"/>'
           '<path d="M76 146V127H122V146" fill="#d8e5ef" stroke="#8da5b8"/>'
           '<rect x="34" y="198" width="25" height="7" fill="#45566a"/>'
           '<rect x="141" y="198" width="25" height="7" fill="#45566a"/>'
           '<text x="100" y="187" text-anchor="middle" font-family="Arial" font-size="10" fill="#45566a">BAMBU LAB P1S</text></svg>')
    return {'type': 'ia.display.image', 'meta': {'name': 'Printer'},
            'position': {'basis': '62px', 'grow': 0, 'shrink': 0},
            'props': {'source': 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode(),
                      'fit': {'mode': 'contain'}, 'style': {'height': '150px'}}}


def row_label(node, basis='0px', grow=1):
    """Labels in a horizontal container need a width, not the default height basis."""
    node['position'].update(basis=basis, grow=grow, shrink=1)
    node['props']['style'].update(minWidth='0', whiteSpace='nowrap', textOverflow='ellipsis')
    return node


def camera_panel(live):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">'
           '<rect width="640" height="360" fill="#172538"/>'
           '<g fill="none" stroke="#70849b" stroke-width="5">'
           '<rect x="265" y="118" width="110" height="80" rx="10"/>'
           '<circle cx="320" cy="158" r="23"/><path d="M285 118l10-16h50l10 16"/></g>'
           '<text x="320" y="240" text-anchor="middle" font-family="Arial" font-size="20" fill="#a8b7c8">'
           + ('Camera unavailable' if live else 'Printer offline') + '</text></svg>')
    placeholder = 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode()
    off_svg = svg.replace('Camera unavailable', 'Camera off')
    off_placeholder = 'data:image/svg+xml;base64,' + base64.b64encode(off_svg.encode()).decode()
    toggle = button('CameraToggle', 'Camera offline')
    toggle['position'].update(basis='36px', grow=0)
    if live:
        toggle = button('CameraToggle', 'Camera Off',
            'self.view.custom.cameraEnabled = not self.view.custom.cameraEnabled')
        toggle['position'].update(basis='36px', grow=0)
        bind(toggle, 'props.text', 'if({view.custom.cameraEnabled}, "Camera Off", "Camera On")')
        bind(toggle, 'props.style.backgroundColor', 'if({view.custom.cameraEnabled}, "#e5f3ed", "#edf1f5")')
    image = {'type': 'ia.display.image', 'meta': {'name': 'CameraImage'},
        'position': {'basis': '276px', 'grow': 0, 'shrink': 0},
        'props': {'source': placeholder, 'altText': 'Printer camera', 'fit': {'mode': 'contain'},
                  'style': {'height': '276px', 'minHeight': '276px', 'maxHeight': '276px',
                            'width': '100%', 'backgroundColor': '#172538'}}}
    if live:
        bind(image, 'props.source', 'if({view.custom.cameraEnabled}, toMillis(now(1000)), 0)')
        image['propConfig']['props.source']['binding']['transforms'] = [{'type': 'script', 'code':
            '\tif not self.view.custom.cameraEnabled:\n'
            '\t    self.view.custom.cameraMessage = "Camera off"\n'
            '\t    return self.parent.custom.offPlaceholder\n'
            '\tframe = bambuP1s.camera_snapshot()\n'
            '\tif not self.view.custom.cameraEnabled:\n'
            '\t    self.view.custom.cameraMessage = "Camera off"\n'
            '\t    return self.parent.custom.offPlaceholder\n'
            '\tself.view.custom.cameraMessage = frame["message"]\n'
            '\treturn frame["source"] or self.parent.custom.placeholder'}]
    message = label('CameraMessage', 'Waiting for camera' if live else 'Not connected',
                    '{view.custom.cameraMessage}' if live else None, 11, 26)
    panel = flex('CameraPanel', [toggle, image, message], style={
        'height': '360px', 'minHeight': '360px', 'maxHeight': '360px',
        'padding': '6px', 'gap': '4px', 'backgroundColor': '#f5f8fb',
        'border': '1px solid #dce4ec', 'borderRadius': '6px', 'overflow': 'hidden'},
        basis='56%', grow=1)
    panel['position']['shrink'] = 1
    if live:
        panel['custom'] = {'placeholder': placeholder, 'offPlaceholder': off_placeholder}
    return panel


def card(number, live=False):
    suffix = '%02d' % number
    status = label('MachineStatus', 'OFFLINE' if not live else 'Awaiting telemetry',
        'if(' + ONLINE + ', ' + tag('Readings/State') + ', "Offline / unknown")' if live else None, 16, 28)
    if live:
        bind(status, 'props.style.color', 'if(' + ONLINE + ', "#146b58", "#7b8795")')
    fields = [label('Program', 'Program: --',
        '"Program: " + if(' + ONLINE + ' && len(' + tag('Readings/FileName') + ') > 0, ' + tag('Readings/FileName') + ', "--")' if live else None, 12, 36)]
    fields[0]['props']['style']['overflowWrap'] = 'anywhere'
    for title, key in [('Nozzle', 'Nozzle'), ('Bed', 'Bed')]:
        expr = ('if(' + ONLINE + ' && ' + tag('Readings/' + key + 'Valid') + ', "' + title + ': " + numberFormat(' +
                tag('Readings/' + key + 'Temp') + ', "0.0") + " °C", "' + title + ': --")')
        fields.append(label(key + 'Temp', title + ': --', expr if live else None, 15, 26))
    fields.append(label('Progress', 'Progress: --',
        'if(' + ONLINE + ' && ' + tag('Readings/ProgressValid') + ', "Progress: " + numberFormat(' + tag('Readings/Progress') + ', "0") + "%", "Progress: --")' if live else None, 13, 24))
    fields.append(label('TimeLeft', 'Time left: --',
        'if(' + ONLINE + ' && ' + tag('Readings/RemainingValid') + ', "Time left: " + numberFormat(ceil(' + tag('Readings/RemainingSeconds') + '/60.0), "0") + " min", "Time left: --")' if live else None, 13, 24))
    header = flex('Header', [row_label(label('PrinterName', 'P1S-' + suffix, size=20, height=32)),
        row_label(label('ConnectionBadge', 'OFFLINE' if not live else 'Awaiting connection',
              'if(' + ONLINE + ', "LIVE · MQTT", "OFFLINE")' if live else None, 12, 25), '112px', 0)], 'row',
        {'height': '36px', 'alignItems': 'center', 'borderBottom': '1px solid #dce4ec', 'paddingBottom': '6px'}, wrap='nowrap')
    buttons = [
        button('Pause', 'Pause', "bambuP1s.command('Pause')" if live else None,
            ONLINE + ' && ' + tag('Readings/State') + ' = "Running" && !' + tag('Commands/Busy') if live else None, '#fff4d9'),
        button('Resume', 'Resume', "bambuP1s.command('Resume')" if live else None,
            ONLINE + ' && ' + tag('Readings/State') + ' = "Paused" && ' + tag('System/ResumeAllowed') + ' && !' + tag('Commands/Busy') if live else None, '#e5f3ed'),
        button('Stop', 'Cancel job', "bambuP1s.command('Stop')" if live else None,
            ONLINE + ' && (' + tag('Readings/State') + ' = "Running" || ' + tag('Readings/State') + ' = "Paused")' if live else None, '#fae9e9'),
        button('PrinterReset', 'Reset', "bambuP1s.system_command('Reset', 'P1S-01')" if live else None,
            tag('Config/ControlRequestsEnabled') if live else None)]
    for node in buttons:
        node['position'].update(basis='0px', shrink=1)
    controls = flex('PrinterButtons', [
        flex('PauseResume', buttons[:2], 'row', {'height': '36px', 'gap': '6px'}, wrap='nowrap'),
        flex('CancelReset', buttons[2:], 'row', {'height': '36px', 'gap': '6px'}, wrap='nowrap')],
        style={'gap': '6px'})
    detail = label('VisionState', 'Vision: not assigned',
        'if(' + FRESH + ' && ' + tag('Vision/TagsGood') + ', "Vision: " + ' + tag('Vision/State') + ' + " · " + ' + tag('Vision/Quality') + ', "Vision: endpoint unavailable")' if live else None, 12, 28)
    readings = flex('Readings', fields, style={'gap': '4px'}, basis='0px', grow=1)
    readings['position']['shrink'] = 1
    machine = flex('MachineAndData', [schematic(), readings], 'row', {'gap': '8px'}, wrap='nowrap')
    left = flex('PrinterDetails', [machine, controls], style={'gap': '10px'}, basis='42%', grow=1)
    left['position']['shrink'] = 1
    nodes = [header,
        flex('StatusLine', [row_label(status, '98px', 0), row_label(detail)], 'row',
             {'height': '28px', 'alignItems': 'center'}, wrap='nowrap'),
        flex('PrinterBody', [left, camera_panel(live)], 'row', {'gap': '12px'}, wrap='nowrap')]
    left['children'].append(label('CommandResult', 'No connection configured' if not live else 'No command requested',
        '"Command: " + ' + tag('Commands/Result') if live else None, 12, 40))
    footer = []
    for name, path in [('Connector', 'Connection/ServiceOnline'), ('MQTT', 'Connection/MqttConnected'), ('Reports', 'Readings/Online')]:
        footer.append(label(name, name + ': offline', '"' + name + ': " + if(' + FRESH + ' && ' + tag(path) + ', "Connected", "Offline / stale")' if live else None, 11, 23))
    footer.append(label('ReportAge', 'Report age: --', 'if(' + ONLINE + ', "Report age: " + numberFormat(' + tag('Readings/AgeSeconds') + ', "0.0") + " s", "Report age: --")' if live else None, 11, 23))
    for node in footer:
        row_label(node)
    left['children'].append(flex('ConnectionDetails', [
        flex('ConnectionRow', footer[:2], 'row', {'height': '23px', 'gap': '10px'}, wrap='nowrap'),
        flex('ReportRow', footer[2:], 'row', {'height': '23px', 'gap': '10px'}, wrap='nowrap')],
        style={'borderTop': '1px solid #dce4ec', 'paddingTop': '8px', 'gap': '2px'}))
    return flex('Printer' + suffix, nodes, style={'padding': '16px', 'backgroundColor': '#ffffff',
        'border': '1px solid #ccd8e3', 'borderRadius': '8px', 'boxShadow': '0 2px 5px #2434480a',
        'opacity': '1' if live else '0.65'}, basis='390px', grow=1)


def main():
    OUT.mkdir(exist_ok=True)
    original = json.loads((HERE / 'original_tags.json').read_text(encoding='utf-8'))
    groups = {g['name']: g for g in original['tags'][0]['tags']}

    def atom(name, dtype, value):
        return {'name': name, 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': dtype, 'value': value}

    groups['Config']['tags'].append(atom('VisionZonePath', 'String', '[default]vLock/A-101'))
    groups['Config']['tags'].append(atom('ControlRequestsEnabled', 'Boolean', True))
    groups['Connection']['tags'].append(atom('MqttConnected', 'Boolean', False))
    groups['Commands']['tags'] += [atom(a, 'Boolean', False) for a in ('Pause', 'Resume', 'Stop', 'Busy')]
    groups['System'] = {'name': 'System', 'tagType': 'Folder', 'tags': [
        atom('Message', 'String', 'Reset, then System Start required'), atom('Events', 'String', '[]'),
        atom('Enabled', 'Boolean', False), atom('StopLatched', 'Boolean', False),
        atom('ResetValid', 'Boolean', False), atom('CanReset', 'Boolean', False),
        atom('ResumeAllowed', 'Boolean', False), atom('HeartbeatMoving', 'Boolean', False),
        atom('StopReason', 'String', '')]}
    next(t for t in groups['System']['tags'] if t['name'] == 'StopLatched')['valuePersistence'] = 'Database'
    groups['Vision'] = {'name': 'Vision', 'tagType': 'Folder', 'tags': [
        atom('TagsGood', 'Boolean', False), atom('State', 'String', 'Unavailable'),
        atom('Quality', 'String', 'Unknown'), atom('Reason', 'String', 'Map the imported zone'),
        atom('BridgeOnline', 'Boolean', False), atom('HeartbeatCounter', 'Int8', 0)]}
    groups['Controls'] = {'name': 'Controls', 'tagType': 'Folder', 'tags': [
        atom('Request', 'String', json.dumps({'schema_version': 1, 'session_id': '', 'sequence': 0,
             'request_id': '', 'action': '', 'target': 'farm', 'requested_at': '',
             'counts': {'Start': 0, 'Stop': 0, 'Reset': 0}})),
        atom('Message', 'String', 'No request; machine action mapping belongs to SCADA'),
        atom('HeartbeatCounter', 'Int8', 0)]}
    tags = [{'name': 'BambuP1S', 'tagType': 'Folder', 'tags': [groups[g] for g in
        ('Config', 'Connection', 'Readings', 'Commands', 'System', 'Vision', 'Controls', 'Camera')]}]
    save(OUT / 'bambu-p1s-tags.json', {'tags': tags})
    bridge = (HERE / 'bridge.py').read_text(encoding='utf-8') + '\n\nTAGS = ' + repr(tags) + '\n'
    (PROJECT / 'ignition/script-python/bambuP1s/code.py').write_text(bridge, encoding='utf-8')
    site = PROJECT / 'ignition/script-python/printerSite'
    site.mkdir(parents=True, exist_ok=True)
    (site / 'code.py').write_text((HERE / 'site_logic.py').read_text(encoding='utf-8'), encoding='utf-8')
    save(site / 'resource.json', {'scope': 'A', 'version': 1, 'restricted': False,
        'overridable': True, 'files': ['code.py'], 'attributes': {}})
    site_timer = PROJECT / 'ignition/timer/printerSiteTick'
    site_timer.mkdir(parents=True, exist_ok=True)
    (site_timer / 'handleTimerEvent.py').write_text('def handleTimerEvent():\n\tprinterSite.tick()\n', encoding='utf-8')
    save(site_timer / 'resource.json', {'scope': 'G', 'version': 1, 'restricted': False,
        'overridable': True, 'files': ['handleTimerEvent.py'],
        'attributes': {'enabled': True, 'delay': 250, 'fixedDelay': True, 'sharedThread': False}})
    legacy = PROJECT / 'ignition/tag-change/PauseOnDetection'
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / 'onTagChange.py').write_text('def onTagChange(initialChange, newValue, previousValue, event, executionCount):\n\tpass  # Replaced by the customer-side printerSiteTick timer.\n', encoding='utf-8')
    save(legacy / 'resource.json', {'scope': 'G', 'version': 1, 'restricted': False,
        'overridable': True, 'files': ['onTagChange.py'], 'attributes': {'enabled': False,
        'changeTypes': ['ValueChange', 'QualityChange'], 'paths': ['[default]vLockBridge/vLock/conveyor_01/Active']}})
    (PROJECT / 'ignition/timer/bambuP1sPoll/handleTimerEvent.py').write_text('def handleTimerEvent():\n\tbambuP1s.tick()\n', encoding='utf-8')
    # Keep one fast dedicated poller; command acknowledgement waiting is asynchronous.
    timer = PROJECT / 'ignition/timer/bambuP1sPoll/resource.json'
    resource = json.loads(timer.read_text())
    resource['attributes'].update(delay=1000, fixedDelay=True, sharedThread=False, enabled=True)
    save(timer, resource)
    save(PROJECT / 'project.json', {'title': 'Printer Farm Control',
        'description': 'One connected P1S and two offline stations; customer Gateway stop latch, reset and operator Resume.',
        'enabled': True, 'inheritable': False, 'parent': ''})
    system = flex('SystemControl', [flex('SystemButtons', [
        button('SystemStart', 'System Start', "bambuP1s.system_command('Start')", tag('Config/ControlRequestsEnabled'), '#e5f3ed'),
        button('SystemStop', 'System Stop', "bambuP1s.system_command('Stop')", tag('Config/ControlRequestsEnabled'), '#fae9e9'),
        button('SystemReset', 'System Reset', "bambuP1s.system_command('Reset')", tag('Config/ControlRequestsEnabled'))], 'row',
        {'maxWidth': '490px', 'height': '36px'}, wrap='nowrap'),
        label('SiteState', 'Reset, then System Start required', tag('System/Message'), size=12, height=26)],
        style={'padding': '10px 14px', 'backgroundColor': '#ffffff', 'border': '1px solid #ccd8e3', 'borderRadius': '8px'})
    events = {'type': 'ia.display.table', 'meta': {'name': 'EventFeed'},
        'position': {'basis': '145px', 'grow': 0, 'shrink': 0},
        'props': {'data': [], 'columns': [{'field': key, 'header': {'title': title}, 'width': width, 'strictWidth': key != 'event'}
            for key, title, width in [('time', 'Time', 90), ('printer', 'Station', 95), ('event', 'Event', 900)]],
            'pager': {'top': False, 'bottom': False}, 'rows': {'height': 28},
            'style': {'fontSize': '12px', 'border': '1px solid #ccd8e3', 'borderRadius': '6px'}}}
    events['propConfig'] = {'props.data': {'binding': {'type': 'tag',
        'config': {'tagPath': ROOT + 'System/Events', 'mode': 'direct'},
        'transforms': [{'type': 'script', 'code': '\ttry:\n\t    return system.util.jsonDecode(str(value))\n\texcept Exception:\n\t    return []'}]}}}
    feedback = label('Feedback', '', '{view.custom.feedback}', size=13, height=32)
    bind(feedback, 'position.display', 'len({view.custom.feedback}) > 0')
    root = flex('Root', [label('Title', 'Printer farm | Operations', size=26, height=40),
        system, flex('PrinterCards', [card(1, True), card(2), card(3)], 'row', {'gap': '18px'}),
        feedback, label('EventsHeading', 'Recent events', size=16), events],
        style={'padding': '22px', 'backgroundColor': '#f2f5f8', 'color': INK,
               'fontFamily': 'Segoe UI, Arial, sans-serif', 'overflow': 'auto', 'gap': '12px'})
    root.pop('position')
    view = {'custom': {'feedback': '', 'cameraEnabled': True, 'cameraMessage': 'Waiting for camera'}, 'params': {},
        'props': {'defaultSize': {'width': 1440, 'height': 1000}}, 'root': root}
    save(PROJECT / 'com.inductiveautomation.perspective/views/PrinterFarm/Dashboard/view.json', view)
    pages = PROJECT / 'com.inductiveautomation.perspective/page-config/config.json'
    config = json.loads(pages.read_text())
    for page in config['pages'].values():
        page['title'] = 'Printer Farm | Operations'
    save(pages, config)
    with ZipFile(OUT / 'printer-farm-perspective.zip', 'w', ZIP_DEFLATED) as archive:
        for path in sorted(PROJECT.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                archive.write(path, path.relative_to(PROJECT).as_posix())
    print('Built', OUT / 'printer-farm-perspective.zip')


if __name__ == '__main__':
    main()
