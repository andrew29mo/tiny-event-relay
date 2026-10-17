"""Install checksum-pinned official binaries into ignored local storage; reuse Docker CLI."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def verified_lima_files(archive, root):
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            target = root / member.name
            if member.issym():
                if not target.is_symlink() or os.readlink(target) != member.linkname:
                    return False
            elif member.isfile():
                if target.is_symlink() or not target.is_file():
                    return False
                expected = hashlib.sha256(stream.extractfile(member).read()).hexdigest()
                if digest(target) != expected:
                    return False
    return True


def install(root=ROOT):
    if platform.system() != 'Darwin':
        raise RuntimeError('Colima host setup requires macOS')
    lock = json.loads((root / 'tools/colima-lock.json').read_text())
    arch = platform.machine()
    toolchain = root / 'results/local/toolchain'
    downloads, binaries = toolchain / 'downloads', toolchain / 'bin'
    downloads.mkdir(parents=True, exist_ok=True)
    binaries.mkdir(exist_ok=True)
    for asset in lock['assets'][arch]:
        archive = downloads / asset['name']
        if not archive.exists() or digest(archive) != asset['sha256']:
            temporary = archive.with_suffix('.download')
            with urllib.request.urlopen(asset['url'], timeout=120) as source, temporary.open('wb') as target:
                shutil.copyfileobj(source, target)
            if digest(temporary) != asset['sha256']:
                raise RuntimeError('Official asset digest mismatch: ' + asset['name'])
            temporary.replace(archive)
        if archive.name.startswith('colima-'):
            target = binaries / 'colima'
            if not target.exists() or digest(target) != asset['sha256']:
                shutil.copyfile(archive, target)
                target.chmod(0o755)
        elif not verified_lima_files(archive, toolchain):
            with tarfile.open(archive) as stream:
                stream.extractall(toolchain, filter='data')
    docker = shutil.which('docker') or '/Applications/Docker.app/Contents/Resources/bin/docker'
    if not Path(docker).is_file():
        raise RuntimeError('Install the Docker CLI; Docker Desktop need not be running')
    target = binaries / 'docker'
    if not target.exists():
        target.symlink_to(Path(docker).resolve())
    runtime = root / 'results/local/runtime'
    # Colima only honors COLIMA_HOME if the directory already exists.
    colima_home = Path.home() / ('.colima-ter-' + hashlib.sha256(str(root).encode()).hexdigest()[:6])
    colima_home.mkdir(parents=True, exist_ok=True)
    for name in ('docker-config/cli-plugins',):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    buildx = shutil.which('docker-buildx') or '/Applications/Docker.app/Contents/Resources/cli-plugins/docker-buildx'
    plugin = runtime / 'docker-config/cli-plugins/docker-buildx'
    if not plugin.exists() and Path(buildx).is_file():
        plugin.symlink_to(Path(buildx).resolve())
    environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ.get('PATH', ''),
                       COLIMA_HOME=str(colima_home), DOCKER_CONFIG=str(runtime / 'docker-config'),
                       DOCKER_HOST='unix://' + str(colima_home / 'relay/docker.sock'))
    environment.pop('DOCKER_CONTEXT', None)
    for binary, expected in [('colima', lock['colima_version']), ('limactl', lock['lima_version'])]:
        output = subprocess.check_output([str(binaries / binary), 'version' if binary == 'colima' else '--version'], env=environment, text=True, timeout=30)
        if expected not in output:
            raise RuntimeError('Installed binary version differs: ' + binary)
    return binaries, environment


if __name__ == '__main__':
    install()
    print('Pinned Colima/Lima installed locally; existing Docker CLI reused.')
