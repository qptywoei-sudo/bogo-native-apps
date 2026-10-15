#!/usr/bin/env python3
"""Export only verified public per-app release assets to the KIO store and native launcher."""
import argparse, json, re
from pathlib import Path

REPOSITORY='qptywoei777-rgb/kio-native-apps'
PREFIX='https://github.com/'+REPOSITORY+'/releases/download/'
SHA=re.compile(r'sha256:([0-9a-f]{64})\Z')

def collect(catalog, releases):
    registry=[]
    for app_id, app in catalog.items():
        app.update(state='building', downloads=[])
        app.pop('releaseUrl', None)
        candidates=[]
        for release in releases:
            tag=release.get('tag_name','')
            match=re.fullmatch(re.escape(app_id)+r'-v([0-9]+\.[0-9]+\.[0-9]+-kio\.[1-9][0-9]*)',tag)
            if not release.get('draft') and match and match[1].split('-kio.')[0] == app['version'].split('-kio.')[0]:
                candidates.append((tuple(map(int,match[1].replace('-kio.','.').split('.'))),release,match[1]))
        if not candidates: continue
        _,release,version=max(candidates,key=lambda x:x[0])
        tag=release['tag_name']; base=app['name'].replace(' ','-')+'-'+version+'-'
        downloads=[]; artifacts=[]
        names=set()
        allowed={'macos-arm64.dmg':('macos','arm64','aarch64','dmg'),
                 'macos-arm64.zip':('macos','arm64','aarch64','app-zip'),
                 'windows-x64.msi':('windows','x64','x86_64','msi'),
                 'windows-x64.zip':('windows','x64','x86_64','portable-zip'),
                 'source.zip':('source','source','source','source')}
        for asset in release.get('assets',[]):
            name=asset.get('name',''); suffix=name[len(base):] if name.startswith(base) else ''
            if suffix not in allowed: continue
            if name in names: raise ValueError('Duplicate asset '+name)
            names.add(name)
            digest=SHA.fullmatch(asset.get('digest') or '')
            url=PREFIX+tag+'/'+name
            if asset.get('browser_download_url')!=url or not digest or not isinstance(asset.get('size'),int) or not 0<asset['size']<2*1024**3 or asset.get('state')!='uploaded':
                raise ValueError('Unverified or unexpected public release asset '+name)
            platform,arch,feed_arch,kind=allowed[suffix]
            downloads.append({'platform':platform,'arch':arch,'url':url,'bytes':asset['size'],'sha256':digest[1],'format':suffix.rsplit('.',1)[1]})
            if platform!='source' and kind!='app-zip':
                artifacts.append({'platform':platform,'arch':feed_arch,'kind':kind,'url':url,'sha256':digest[1],'bytes':asset['size']})
        if not artifacts or not any(x['platform']=='source' for x in downloads): continue
        app.update(state='released',version=version,releaseUrl='https://github.com/'+REPOSITORY+'/releases/tag/'+tag,downloads=downloads)
        registry.append({'id':app_id,'name':app['name'],'version':version,'upstreamVersion':version.split('-kio.')[0],'releaseTag':tag,'repository':REPOSITORY,'bundleId':'com.kio.'+app_id,'artifacts':artifacts})
    return {'schemaVersion':1,'programs':registry}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--releases-json',type=Path,required=True)
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--feed',type=Path,required=True)
    args=parser.parse_args()
    original=args.catalog.read_text(); marker='export const KIO_NATIVE_APPS = Object.freeze('
    start=original.index(marker)+len(marker); end=original.index(');\nexport function getKioNativeApp',start)
    catalog=json.loads(original[start:end]); releases=json.loads(args.releases_json.read_text())
    feed=collect(catalog,releases)
    args.catalog.write_text(original[:start]+json.dumps(catalog,ensure_ascii=False,indent=2)+original[end:])
    args.feed.parent.mkdir(parents=True,exist_ok=True)
    args.feed.write_text(json.dumps(feed,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'released':[p['id'] for p in feed['programs']],'assets':sum(len(p['artifacts']) for p in feed['programs'])}))

if __name__=='__main__': main()
