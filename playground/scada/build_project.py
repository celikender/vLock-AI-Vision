"""Build a native Perspective import ZIP from the reviewed project resources."""
import base64
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

HERE = Path(__file__).resolve().parent
PROJECT = HERE / 'project'
OUT = HERE / 'output'
ROOT = '[default]BambuP1S/'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def tag(path):
    return '{' + ROOT + path + '}'


FRESH = '(!isNull(' + tag('Connection/LastPoll') + ') && secondsBetween(' + tag('Connection/LastPoll') + ', now(1000)) >= 0 && secondsBetween(' + tag('Connection/LastPoll') + ', now(1000)) < 10)'
ONLINE = '(' + FRESH + ' && ' + tag('Readings/Online') + ')'


def bind(node, prop, expression):
    node.setdefault('propConfig', {})[prop] = {'binding': {'type': 'expr', 'config': {'expression': expression}}}
    return node


def label(name, text, expression=None, size=16, height=32):
    node = {'type': 'ia.display.label', 'meta': {'name': name},
            'position': {'basis': str(height) + 'px', 'grow': 0, 'shrink': 0},
            'props': {'text': text, 'style': {'fontSize': str(size) + 'px', 'whiteSpace': 'normal', 'color': '#20252b'}}}
    if expression:
        bind(node, 'props.text', expression)
    return node


def flex(name, children, direction='column', style=None, basis='auto', grow=0):
    return {'type': 'ia.container.flex', 'meta': {'name': name},
            'position': {'basis': basis, 'grow': grow, 'shrink': 0},
            'props': {'direction': direction, 'wrap': 'wrap' if direction == 'row' else 'nowrap',
                      'justify': 'flex-start', 'alignItems': 'stretch',
                      'style': dict({'boxSizing': 'border-box', 'gap': '12px'}, **(style or {}))},
            'children': children}


def button(name, text, call, enabled=None, color='#ffffff'):
    n = {'type': 'ia.input.button', 'meta': {'name': name},
         'position': {'basis': '130px', 'grow': 0, 'shrink': 0},
         'props': {'text': text, 'enabled': False if enabled else True, 'primary': False,
                   'style': {'backgroundColor': color, 'color': '#20252b', 'border': '1px solid #929ba4',
                             'borderRadius': '3px', 'height': '42px', 'fontSize': '15px'}},
         'events': {'component': {'onActionPerformed': {'type': 'script', 'scope': 'G',
                    'config': {'script': '\ttry:\n\t    ' + call + '\n\t    self.view.custom.feedback = ""\n\texcept Exception as exc:\n\t    self.view.custom.feedback = str(exc)'}}}}}
    if enabled:
        bind(n, 'props.enabled', enabled)
    return n


def main():
    OUT.mkdir(exist_ok=True)
    original = json.loads((HERE / 'original_tags.json').read_text(encoding='utf-8'))
    groups = {g['name']: g for g in original['tags'][0]['tags']}
    def atom(name, dtype, value):
        return {'name': name, 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': dtype, 'value': value}
    readings = {'Online', 'State', 'RawState', 'NozzleTemp', 'BedTemp', 'AgeSeconds', 'NozzleValid', 'BedValid'}
    groups['Readings']['tags'] = [t for t in groups['Readings']['tags'] if t['name'] in readings]
    groups['Connection']['tags'].append(atom('MqttConnected', 'Boolean', False))
    groups['Commands']['tags'] += [atom(a, 'Boolean', False) for a in ('Pause', 'Resume', 'Stop', 'Busy')]
    groups['System'] = {'name': 'System', 'tagType': 'Folder', 'tags': [atom('Enabled', 'Boolean', False), atom('Message', 'String', 'Stopped; vLock pending')]}
    tags = [{'name': 'BambuP1S', 'tagType': 'Folder', 'tags': [groups[g] for g in ('Config','Connection','Readings','Commands','System')]}]
    save(OUT / 'bambu-p1s-tags.json', {'tags': tags})
    bridge = (HERE / 'bridge.py').read_text(encoding='utf-8')
    bridge += '\n\nTAGS = ' + repr(tags) + '\n'
    (PROJECT / 'ignition/script-python/bambuP1s/code.py').write_text(bridge, encoding='utf-8')
    timer = PROJECT / 'ignition/timer/bambuP1sPoll/handleTimerEvent.py'
    timer.write_text('def handleTimerEvent():\n\tbambuP1s.tick()\n', encoding='utf-8')
    (PROJECT / 'ignition/timer/printerFarmTick/handleTimerEvent.py').write_text('def handleTimerEvent():\n\tpass\n', encoding='utf-8')
    save(PROJECT / 'project.json', {'title': 'Single Printer Control', 'description': 'One P1S: live temperatures, status, printer commands and separate supervisory controls.', 'enabled': True, 'inheritable': False, 'parent': ''})
    # A simple printer schematic, built as a native image source without external assets.
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="280" height="240" viewBox="0 0 280 240"><rect x="35" y="12" width="210" height="207" rx="4" fill="#f5f6f7" stroke="#39424c" stroke-width="5"/><rect x="52" y="37" width="176" height="151" fill="white" stroke="#9da5ad" stroke-width="2"/><path d="M60 67H220 M140 68V102 M132 102H148L140 116Z M65 163H215 M78 171H202" fill="none" stroke="#39424c" stroke-width="5"/><path d="M105 159V137H171V159" fill="#e5e9ec" stroke="#78838e" stroke-width="2"/><rect x="48" y="220" width="35" height="8" fill="#39424c"/><rect x="197" y="220" width="35" height="8" fill="#39424c"/><text x="140" y="208" text-anchor="middle" font-family="Arial" font-size="12" fill="#39424c">BAMBU LAB P1S</text></svg>'
    image = {'type': 'ia.display.image', 'meta': {'name': 'Printer'}, 'position': {'basis': '240px', 'grow': 0, 'shrink': 0}, 'props': {'source': 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode(), 'fit': {'mode':'contain'}}}
    system = flex('SystemControl', [label('Heading', 'System control', size=20),
        flex('SystemButtons', [button('SystemStart', 'System Start', "bambuP1s.system_command('Start')", color='#e8f1e9'), button('SystemStop','System Stop', "bambuP1s.system_command('Stop')",color='#f6e8e8'), button('SystemReset','System Reset', "bambuP1s.system_command('Reset')")], 'row'),
        label('SystemState','Stopped; vLock pending', 'if(' + FRESH + ', ' + tag('System/Message') + ', "System status unavailable")'),
        label('SystemMeaning','Supervisory enable only. Printer operation is separate. vLock is not connected.',size=13,height=32)],
        style={'border':'1px solid #b9c0c7','padding':'16px','backgroundColor':'#f5f6f7'})
    data = [label('MachineStatus','Machine: Offline','"Machine: " + if(' + ONLINE + ', ' + tag('Readings/State') + ', "Offline / unknown")',size=20,height=40)]
    for title,key in [('Nozzle','Nozzle'),('Bed','Bed')]:
        expr='if(' + ONLINE + ' && ' + tag('Readings/'+key+'Valid') + ', "' + title + ': " + numberFormat(' + tag('Readings/'+key+'Temp') + ', "0.0") + " deg C", "' + title + ': --")'
        data.append(label(key+'Temp',title+': --',expr,size=23,height=40))
    for name,path in [('Connector','Connection/ServiceOnline'),('MQTT','Connection/MqttConnected'),('Printer reports','Readings/Online')]:
        data.append(label(name.replace(' ',''),name+': unavailable', '"' + name + ': " + if(' + FRESH + ' && ' + tag(path) + ', "Connected", "Disconnected / stale")',height=26))
    data.append(label('ReportAge','Report age: --','if(' + ONLINE + ', "Report age: " + numberFormat(' + tag('Readings/AgeSeconds') + ', "0.0") + " s", "Report age: --")'))
    controls = flex('PrinterButtons', [
        button('Pause','Pause',"bambuP1s.command('Pause')",ONLINE+' && '+tag('Readings/State')+' = "Running" && !'+tag('Commands/Busy'), '#fff3d6'),
        button('Resume','Resume',"bambuP1s.command('Resume')",ONLINE+' && '+tag('Readings/State')+' = "Paused" && '+tag('System/Enabled')+' && !'+tag('Commands/Busy'),'#e8f1e9'),
        button('Stop','Stop / cancel',"bambuP1s.command('Stop')",ONLINE+' && ('+tag('Readings/State')+' = "Running" || '+tag('Readings/State')+' = "Paused")','#f6e8e8')], 'row')
    machine = flex('PrinterPanel', [label('PrinterTitle','Bambu Lab P1S',size=24,height=40),
        flex('MachineAndData',[flex('Schematic',[image],basis='280px'),flex('Readings',data,style={'gap':'6px'},basis='300px',grow=1)],'row'),
        controls, label('ControlMeaning','Resume continues a paused job. Stop cancels the job; it is not an emergency stop.',size=13,height=40),
        label('CommandResult','No command requested','"Printer command: " + '+tag('Commands/Result'),height=60)],
        style={'border':'1px solid #b9c0c7','padding':'16px'})
    root=flex('Root',[label('Title','Single printer control',size=26,height=44),system,machine,
        label('DataFlow','P1S -> MQTT connector -> Ignition tags -> this screen',size=13),
        label('Feedback','', '{view.custom.feedback}',size=13,height=50)],style={'padding':'20px','backgroundColor':'#ffffff','color':'#20252b','fontFamily':'Segoe UI, Arial, sans-serif','overflow':'auto'})
    root.pop('position')
    view={'custom':{'feedback':''},'params':{},'props':{'defaultSize':{'width':1000,'height':900}},'root':root}
    save(PROJECT / 'com.inductiveautomation.perspective/views/PrinterFarm/Dashboard/view.json',view)
    with ZipFile(OUT / 'single-printer-perspective.zip','w',ZIP_DEFLATED) as archive:
        for path in sorted(PROJECT.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                archive.write(path,path.relative_to(PROJECT).as_posix())
    print('Built', OUT / 'single-printer-perspective.zip')


if __name__ == '__main__':
    main()
