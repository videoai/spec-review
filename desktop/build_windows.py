#!/usr/bin/env python3
"""Build an unsigned portable Windows x64 app; run on a Windows build machine."""
import hashlib,os,shutil,subprocess,sys,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
DIST=ROOT/'dist';OUTPUT=DIST/'ONVIF-Spec-Review-Windows-x64'
DEPENDENCIES={
    'git':('https://github.com/git-for-windows/git/releases/download/v2.56.1.windows.1/MinGit-2.56.1-64-bit.zip','4a92850b6e917da4fd010669b614b55dccf5b0ec333a534cc4be4700dfefdafd'),
    'gh':('https://github.com/cli/cli/releases/download/v2.104.0/gh_2.104.0_windows_amd64.zip','08c06d10482f12c478018cd259f64acbd5f625712cadf331aad19ba973c879e5')}

def run(*args,**kwargs):subprocess.run([str(arg) for arg in args],check=True,**kwargs)
def download(name,url,digest):
    cache=ROOT/'.cache/windows';cache.mkdir(parents=True,exist_ok=True);archive=cache/(name+'.zip')
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest()!=digest:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'ONVIF-Spec-Review-build'}),timeout=120) as response:payload=response.read()
        if hashlib.sha256(payload).hexdigest()!=digest:raise ValueError('Checksum mismatch for '+name)
        archive.write_bytes(payload)
    return archive

def main():
    if sys.platform!='win32':raise SystemExit('Build Windows executables on Windows (use the Windows build workflow).')
    os.chdir(ROOT);DIST.mkdir(exist_ok=True)
    if OUTPUT.exists():shutil.rmtree(OUTPUT)
    run(sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--name','spec-review-service',*[arg for asset in ('index.html','app.js','review-core.js','pages.js') for arg in ('--add-data',asset+':.')],'desktop_service.py')
    run('dotnet','publish','desktop/windows/SpecReview.csproj','--configuration','Release','--runtime','win-x64','--self-contained','true','--output',OUTPUT,'-p:DebugType=None','-p:DebugSymbols=false')
    shutil.copytree(DIST/'spec-review-service',OUTPUT/'backend')
    for name,(url,digest) in DEPENDENCIES.items():
        destination=OUTPUT/'tools'/name;destination.mkdir(parents=True)
        with zipfile.ZipFile(download(name,url,digest)) as archive:archive.extractall(destination)
    # GitHub CLI release zips currently contain bin/gh.exe at the root.
    if not (OUTPUT/'tools/gh/bin/gh.exe').exists():
        executable=next((OUTPUT/'tools/gh').rglob('gh.exe'));(OUTPUT/'tools/gh/bin').mkdir(exist_ok=True);shutil.copy2(executable,OUTPUT/'tools/gh/bin/gh.exe')
    if not (OUTPUT/'tools/git/cmd/git.exe').exists():raise ValueError('MinGit layout changed: cmd/git.exe missing')
    run(OUTPUT/'tools/git/cmd/git.exe','--version');run(OUTPUT/'tools/gh/bin/gh.exe','--version')
    # Check copied DLLs, Git, private HTTP session, notes, suggestions and summary folding.
    run(sys.executable,'desktop/smoke_backend.py','--package',OUTPUT)
    shutil.copy2(ROOT/'desktop/windows/READ ME.txt',OUTPUT/'READ ME.txt')
    licenses=OUTPUT/'Licenses';licenses.mkdir()
    shutil.copy2(ROOT/'desktop/windows/DEPENDENCIES.txt',licenses/'DEPENDENCIES.txt')
    archive=shutil.make_archive(str(DIST/'ONVIF-Spec-Review-Windows-x64'),'zip',root_dir=DIST,base_dir=OUTPUT.name)
    print('Built '+archive,flush=True)
if __name__=='__main__':main()
