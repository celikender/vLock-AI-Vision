"""Apply the upstream SAM session-argument compatibility fix to this runtime."""
import importlib.util
from pathlib import Path


def main():
    spec = importlib.util.find_spec('sam3')
    path = Path(spec.origin).parent / 'model' / 'sam3_base_predictor.py'
    source = path.read_text()
    marker = '        # Filter session arguments for the selected model variant.\n'
    if marker in source:
        print('Session compatibility fix already installed.')
        return
    old = '        inference_state = self.model.init_state(**init_kwargs)\n'
    new = (marker + '        import inspect\n'
           '        valid_params = inspect.signature(self.model.init_state).parameters\n'
           '        init_kwargs = {k: v for k, v in init_kwargs.items() if k in valid_params}\n' + old)
    if source.count(old) != 1:
        raise RuntimeError('Unexpected SAM source; inspect before patching.')
    updated = source.replace(old, new)
    compile(updated, str(path), 'exec')
    backup = path.with_suffix('.py.before-session-fix')
    if backup.exists():
        raise RuntimeError('Existing backup found; inspect before patching.')
    backup.write_text(source)
    path.write_text(updated)
    print('Installed session compatibility fix; original source preserved beside it.')


if __name__ == '__main__':
    main()
