"""Local connector settings window. Credentials remain on this PC."""
from pathlib import Path
import argparse
import tkinter as tk
from tkinter import ttk, messagebox

from p1s_service import Config, read_env

HOME = Path(__file__).resolve().parent


def main(config_dir=HOME):
    path = Path(config_dir) / '.env'
    values = read_env(path)
    root = tk.Tk()
    root.title('Bambu P1S connector settings')
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=20)
    frame.grid()
    ttk.Label(frame, text='Printer connection', font=('Segoe UI', 15, 'bold')).grid(
        row=0, column=0, columnspan=2, sticky='w', pady=(0, 12))
    fields = [('BAMBU_IP', 'Printer IP'), ('BAMBU_SERIAL', 'Serial number (S/N)'),
              ('BAMBU_ACCESS_CODE', 'LAN access code')]
    variables = {}
    for row, (key, label) in enumerate(fields, 1):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=(0, 15), pady=5)
        variables[key] = tk.StringVar(value=values.get(key, '192.168.1.100' if key == 'BAMBU_IP' else ''))
        ttk.Entry(frame, textvariable=variables[key], width=40,
                  show='*' if key == 'BAMBU_ACCESS_CODE' else '').grid(row=row, column=1, pady=5)
    camera = tk.BooleanVar(value=values.get('CAMERA_ENABLED', 'false').lower() == 'true')
    ttk.Checkbutton(frame, text='Enable printer camera', variable=camera).grid(
        row=4, column=0, columnspan=2, sticky='w', pady=12)
    ttk.Label(frame, text='Saving settings restarts the installed connector.\n'
              'Existing job settings and certificate pins are preserved.', foreground='#555').grid(
        row=5, column=0, columnspan=2, sticky='w', pady=8)
    saved = [False]

    def save():
        updated = dict(values)
        updated.update({key: var.get().strip() for key, var in variables.items()})
        updated['CAMERA_ENABLED'] = 'true' if camera.get() else 'false'
        updated.setdefault('CONNECTOR_PORT', '8876')
        try:
            if any('\n' in str(v) or '\r' in str(v) for v in updated.values()):
                raise ValueError('Values must fit on one line.')
            if not Config(updated).configured:
                raise ValueError('Enter the printer serial number and LAN access code.')
            path.write_text('\n'.join(key + '=' + value for key, value in updated.items()) + '\n',
                            encoding='utf-8')
        except (ValueError, TypeError, OSError) as exc:
            messagebox.showerror('Check settings', str(exc))
            return
        saved[0] = True
        root.destroy()

    ttk.Button(frame, text='Save', command=save).grid(row=6, column=1, sticky='e', pady=8)
    root.mainloop()
    return 0 if saved[0] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config-dir', type=Path, default=HOME)
    raise SystemExit(main(parser.parse_args().config_dir))
