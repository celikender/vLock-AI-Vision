"""Build one deployment bundle with one import archive and one connector copy."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import build_project

HERE = Path(__file__).resolve().parent
CONNECTOR_FILES = ('p1s_service.py', '.env.example', 'requirements.txt', 'configure.py',
                   'Install.ps1', 'Manage.ps1', 'Setup.cmd', 'Configure.cmd', 'Restart.cmd')


def main():
    build_project.main()
    destination = HERE / 'output/printer-farm.zip'
    files = {name: HERE / 'connector' / name for name in CONNECTOR_FILES}
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        archive.write(HERE / 'PACKAGE_README.md', 'START_HERE.md')
        archive.write(HERE / 'output/printer-farm-perspective.zip', 'printer-farm-perspective.zip')
        archive.write(HERE / 'output/bambu-p1s-tags.json', 'bambu-p1s-tags.json')
        for name, path in files.items():
            archive.write(path, 'connector/' + name)
    print('Built', destination)


if __name__ == '__main__':
    main()
