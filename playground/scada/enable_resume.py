"""Run once as administrator on the connector PC; restart the service afterward."""
import ast
from datetime import datetime
from pathlib import Path


def patched(source):
    if "'Resume': 'resume'" in source or '"Resume": "resume"' in source:
        return source
    tree = ast.parse(source)
    methods = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in ('execute', '_execute')}
    if set(methods) != {'execute', '_execute'}:
        raise ValueError('Reviewed connector methods not found; nothing changed')
    edits = 0
    for n in ast.walk(methods['execute']):
        if isinstance(n, ast.Tuple) and [getattr(e, 'value', None) for e in n.elts] == ['Start', 'Pause', 'Stop', 'Reset']:
            n.elts.append(ast.Constant('Resume'))
            edits += 1
    method = methods['_execute']
    for i, n in enumerate(method.body):
        if isinstance(n, ast.Assign) and ast.unparse(n) == 's = self.status()':
            guard = ast.parse("if action == 'Resume' and s['state'] != 'Paused':\n    raise UserError('Resume requires a paused print')").body[0]
            method.body.insert(i + 1, guard)
            edits += 1
            break
    for n in ast.walk(method):
        if isinstance(n, ast.Dict) and [getattr(k, 'value', None) for k in n.keys] == ['Start', 'Pause', 'Stop']:
            n.keys.append(ast.Constant('Resume'))
            n.values.append(ast.parse("'resume'" if isinstance(n.values[0], ast.Constant) else "('Running',)", mode='eval').body)
            edits += 1
    if edits != 4:
        raise ValueError('Connector source differs from the reviewed version; nothing changed')
    lines = source.splitlines(keepends=True)
    for method in sorted(methods.values(), key=lambda m: m.lineno, reverse=True):
        ast.fix_missing_locations(method)
        replacement = '\n'.join('    ' + line for line in ast.unparse(method).splitlines()) + '\n'
        lines[method.lineno - 1:method.end_lineno] = [replacement]
    source = ''.join(lines)
    ast.parse(source)
    return source


if __name__ == '__main__':
    target = Path(r'C:\ProgramData\BambuP1SConnector\p1s_service.py')
    original = target.read_text(encoding='utf-8-sig')
    updated = patched(original)
    if updated == original:
        print('Resume action is already present; no changes made.')
    else:
        backup = target.with_name('p1s_service.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.py')
        backup.write_bytes(target.read_bytes())
        target.write_text(updated, encoding='utf-8')
        print('Added Resume action. Original source backed up beside the service script.')
        print('Restart the BambuP1SConnector service to load the change.')
