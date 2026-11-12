#!/usr/bin/env python3
"""Build the local Apple Silicon prototype. Requires Swift CLT, PyInstaller and brew git/gh."""
import os, plistlib, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
DIST=ROOT/'dist';APP=DIST/'ONVIF Spec Review.app';CONTENTS=APP/'Contents';RES=CONTENTS/'Resources';TOOLS=RES/'tools'

def run(*args,**kw):subprocess.run([str(x) for x in args],check=True,**kw)
def brew_prefix(name):return Path(subprocess.check_output(['brew','--prefix',name],text=True).strip())
def bundle_binary(source,destination):
    destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
    queue=[destination];seen=set()
    while queue:
        file=queue.pop()
        if file in seen:continue
        seen.add(file)
        dependencies=subprocess.check_output(['otool','-L',str(file)],text=True).splitlines()[1:]
        for line in dependencies:
            name=line.strip().split(' (')[0]
            if not name.startswith('/opt/homebrew/'):continue
            target=TOOLS/'lib'/Path(name).name
            if not target.exists():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(name,target);queue.append(target)
            relative=os.path.relpath(target,file.parent)
            run('install_name_tool','-change',name,'@loader_path/'+relative,file)
        if file.suffix=='.dylib':run('install_name_tool','-id','@loader_path/'+file.name,file)
    for file in seen:run('codesign','--force','--sign','-',file)

os.chdir(ROOT)
if APP.exists():shutil.rmtree(APP)
(CONTENTS/'MacOS').mkdir(parents=True);TOOLS.mkdir(parents=True);(RES/'templates').mkdir()
env=dict(os.environ,PYINSTALLER_CONFIG_DIR='/tmp/onvif-review-pyinstaller')
run(sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--name','spec-review-service','--add-data','index.html:.','--add-data','app.js:.','--add-data','review-core.js:.','--add-data','pages.js:.','--workpath','/tmp/onvif-review-pywork','desktop_service.py',env=env)
shutil.copytree(DIST/'spec-review-service',RES/'backend')
run('swiftc','-module-cache-path','/tmp/onvif-review-swift-cache','desktop/Main.swift','-o',CONTENTS/'MacOS/SpecReview','-framework','AppKit','-framework','WebKit')
git=brew_prefix('git');gh=brew_prefix('gh')
bundle_binary(git/'bin/git',TOOLS/'git');bundle_binary(git/'libexec/git-core/git-remote-http',TOOLS/'git-core/git-remote-http');(TOOLS/'git-core/git-remote-https').symlink_to('git-remote-http')
bundle_binary(gh/'bin/gh',TOOLS/'gh')
licenses=RES/'Licenses';licenses.mkdir()
for name in ('git','gh','pcre2','gettext','libunistring'):
    base=brew_prefix(name)
    matches=[path for path in base.rglob('*') if path.is_file() and (path.name.startswith(('COPYING','LICENSE')) or path.name=='copyright')]
    folder=licenses/name;folder.mkdir()
    for index,path in enumerate(matches):shutil.copy2(path,folder/(str(index)+'-'+path.name))
(licenses/'Sources.txt').write_text('Bundled open-source components:\nGit: https://github.com/git/git (version '+subprocess.check_output([str(git/'bin/git'),'--version'],text=True).strip()+')\nGitHub CLI: https://github.com/cli/cli\nPython: https://www.python.org/\nPyInstaller: https://pyinstaller.org/\nHomebrew dependency sources/recipes: https://github.com/Homebrew/homebrew-core\nThis is a local development prototype, not a signed public release.\n')
info={'CFBundleName':'ONVIF Spec Review','CFBundleDisplayName':'ONVIF Spec Review','CFBundleIdentifier':'com.videoai.onvif-spec-review','CFBundleExecutable':'SpecReview','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.1.0','CFBundleVersion':'1','NSHighResolutionCapable':True,'LSMinimumSystemVersion':'26.0','NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}
(CONTENTS/'Info.plist').write_bytes(plistlib.dumps(info))
run('codesign','--force','--deep','--sign','-',APP)
print('Built '+str(APP))
