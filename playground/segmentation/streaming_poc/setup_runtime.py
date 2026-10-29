"""Create an ignored, isolated Transformers overlay; never install into the working runtime."""
import argparse
import subprocess
import sys
import sysconfig
import venv
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',default='5.21.0')
    args=parser.parse_args()
    if sys.platform!='linux':
        parser.error('Run with the existing Ubuntu CUDA Python.')
    destination=Path(__file__).resolve().parents[2]/'outputs'/'streaming-env-linux'
    if Path(sys.prefix).resolve()==destination:
        parser.error('Run setup from the original CUDA environment, not the overlay.')
    base_packages=Path(sysconfig.get_path('purelib')).resolve()
    venv.EnvBuilder(with_pip=True,system_site_packages=False).create(destination)
    overlay_packages=destination/'lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
    (overlay_packages/'cuda_runtime.pth').write_text(str(base_packages)+'\n')
    python=destination/'bin'/'python'
    subprocess.run([str(python),'-m','pip','install','--no-compile','--upgrade-strategy','only-if-needed',
                    f'transformers=={args.version}'],check=True)
    print(f'Isolated Python: {python}',flush=True)


if __name__=='__main__':
    main()
