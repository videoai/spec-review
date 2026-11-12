#!/usr/bin/env python3
"""Build a static public PR viewer. Runs trusted tool code; reads PR files as data only."""
import argparse
import hashlib
import json
import re
import shutil
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import server


def safe_svg(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise ValueError('Unsafe SVG declarations')
    root=ET.fromstring(data)
    allowed=set('svg g defs path rect circle ellipse line polyline polygon text tspan textPath title desc use symbol marker pattern clipPath mask linearGradient radialGradient stop filter feGaussianBlur feOffset feBlend feColorMatrix feComposite feFlood feMerge feMergeNode style'.split())
    def css_safe(value):
        # No escaped URLs, imports, or resource loads outside this SVG.
        return '\\' not in value and '@' not in value and 'url(' not in re.sub(r'''url\(\s*(['"]?)#[a-zA-Z0-9_:.-]+\1\s*\)''','',value,flags=re.I).lower()
    def clean(element):
        for child in list(element):
            if server.name(child) not in allowed or child.tag.startswith('{') and not child.tag.startswith('{http://www.w3.org/2000/svg}'):
                element.remove(child)
            else:clean(child)
        for attr,value in list(element.attrib.items()):
            local=attr.split('}')[-1].lower()
            if local.startswith('on') or local in ('href','src') and not value.startswith('#') or not css_safe(value):del element.attrib[attr]
        if server.name(element)=='style' and not css_safe(element.text or ''):element.text=''
    clean(root)
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


def build_site(output,prs):
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise ValueError('Output directory must be empty; use a new build directory.')
    output.mkdir(parents=True,exist_ok=True);(output/'data').mkdir();(output/'assets').mkdir()
    repo=server.github_repo();built=datetime.datetime.now(datetime.timezone.utc).isoformat();catalog=[]
    tool=Path(__file__).parent
    for name in ('app.js','review-core.js','pages.js'):shutil.copyfile(tool/name,output/name)
    markup=(tool/'index.html').read_text().replace('<script src="./app.js" defer>', '<script src="./pages.js" defer></script><script src="./app.js" defer>')
    # Static data is sanitized and scripts are loaded only from this origin.
    policy="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https://api.github.com; object-src 'none'; base-uri 'self'; form-action 'none'"
    markup=markup.replace('<meta charset="utf-8">','<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="'+policy+'">')
    (output/'index.html').write_text(markup);(output/'.nojekyll').write_text('')
    def asset(match):
        url=server.html.unescape(match.group(0));query=parse_qs(urlparse(url).query)
        data=server.git('cat-file','blob',query['blob'][0]) if 'blob' in query else server.source(query['ref'][0],query['path'][0])
        mime=server.image_mime(data)
        if not mime:raise ValueError('Unsupported exported image')
        if mime=='image/svg+xml':data=safe_svg(data)
        ext={'image/png':'png','image/jpeg':'jpg','image/gif':'gif','image/webp':'webp','image/svg+xml':'svg'}[mime]
        name=hashlib.sha256(data).hexdigest()+'.'+ext;(output/'assets'/name).write_bytes(data)
        return './assets/'+name
    for item in prs:
        number=item['number'];descriptor={key:item[key] for key in ('number','title','labels') if key in item}
        try:
            pr=server.resolve_pr(number)
            # Do not deploy stale metadata as a fresh comparison.
            if pr.get('github',{}).get('stale'):raise ValueError('GitHub metadata is stale; rebuild after GitHub is available.')
            pr.pop('github',None);comparisons={}
            for path in pr['files']:
                try:
                    result=server.comparison(pr['left'],pr['right'],path)
                    changes=[row for row in result['rows'] if row['status']!='same']
                    doc={'path':path,'mode':result['mode'],'changes':changes}
                    anchors=server.chunk_anchors(pr['left'],pr['right'],doc)
                    for row,anchor in zip(changes,anchors):row['anchor']=anchor
                    for row in result['rows']:
                        row['reviewed']=False
                        for side in ('left','right'):row[side]=re.sub(r'/api/asset\?[^\s\"<>]+',asset,row[side])
                    comparisons[path]=result
                except Exception as error:comparisons[path]={'error':str(error)}
            payload=json.dumps({'pr':pr,'comparisons':comparisons},ensure_ascii=False,separators=(',',':')).encode()
            name='data/pr-'+str(number)+'-'+hashlib.sha256(payload).hexdigest()[:16]+'.json';(output/name).write_bytes(payload)
            descriptor['data']=name
        except Exception as error:descriptor['error']=str(error)
        catalog.append(descriptor)
    manifest={'format':'onvif-spec-review-site','version':1,'repository':repo,'builtAt':built,'prs':catalog}
    (output/'site.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    size=sum(file.stat().st_size for file in output.rglob('*') if file.is_file())
    if size>900*1024*1024:raise ValueError('Generated site exceeds the 900 MB safety budget; reduce published PRs/assets.')
    return {'prs':len(catalog),'bytes':size,'errors':[item for item in catalog if item.get('error')]}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=server.REPO);p.add_argument('--output',type=Path,required=True);p.add_argument('--pr',type=int,action='append');p.add_argument('--fetch',action='store_true');args=p.parse_args();server.REPO=args.repo.resolve()
    if server.github_repo().lower()!=server.TARGET_REPOSITORY:raise ValueError('This viewer currently supports only onvif/specs.')
    metadata=server.github_api('repos/'+server.github_repo(),force=True)
    if metadata.get('private') is not False or getattr(server.API_INFO,'value',{}).get('stale'):raise ValueError('Static publication requires a verified public GitHub repository.')
    if args.fetch:server.git('fetch','--no-tags','origin','+refs/heads/*:refs/remotes/origin/*')
    listing=server.list_prs(force=True)
    if listing.get('github',{}).get('stale'):raise ValueError('Cannot publish using stale PR metadata')
    prs=[item for item in listing['prs'] if not args.pr or item['number'] in args.pr]
    if args.pr and set(args.pr)-{item['number'] for item in prs}:raise ValueError('Requested PR is not open or is from a fork')
    result=build_site(args.output,prs);print(json.dumps(result,indent=2))
    if result['errors']:raise SystemExit('Some PRs could not be built. Existing deployment is preserved; inspect build errors.')

if __name__=='__main__':main()
