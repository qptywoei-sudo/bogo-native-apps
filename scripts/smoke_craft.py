#!/usr/bin/env python3
"""Synthetic file-format QA for explicitly supplied full native Craft CLIs.

No builds, installs, GUI control, model downloads, server attachment or user files.
An unexecuted --plan is never a passing application test.
"""
import argparse
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import time
import wave
import zlib
from pathlib import Path
import xml.etree.ElementTree as ET

APPS = {
 'photo':('photocraft','0.9.0','c699e3cda69f4852b43c0b191ab0091aaeff9d6a','layered .pcraft; lossless PNG roundtrip; paint stroke and layer retention'),
 'vector':('vectorcraft','0.11.0','0a33cff3f6e2a1e9e672f4c3816f58cd8d3d032e','native .vectorcraft; editable geometry; SVG/PNG/PDF exports and native reopen'),
 'film':('filmcraft','0.8.0','f03e21556d8e3a7155b91892d958debd5255d7af','native .fcproj; synthetic timeline placement/razor; rendered pixels and encoded MP4 probe'),
 'light':('lightcraft','0.8.0','16dbb90499d3c63a6582fcbba1b2550a6e2da032','synthetic image develop/exposure; persisted settings; PNG/JPEG and original plus editable XMP exports'),
 'pdf':('pdfcraft','0.8.0','9931329b9fae0b05373b4dc3ac7c58541f0891a4','synthetic PDF structural edits/save/reopen; title/rotation/page content and raster render'),
 'effect':('effectcraft','0.10.0','05955c08b4fd025f1a09882df72e6dbff1a8148a','native .ecproj composition; keyframe interpolation and rendered solid pixels'),
 'design':('designcraft','0.8.0','11a51d5b665aec8d6e675bd107a8a01514f10d00','native .designcraft text layout; IDML roundtrip, EPUB/PDF/PNG export'),
 'ui':('figcraft','0.6.0','833f0d2c27f0acbae5394848930ae531fc89c724','native .figcraft frames; native/JSON roundtrip and scaled PNG/SVG export'),
 'sound':('soundcraft','0.7.0','3a28a657692c1b98b28c276d8f61df9471074f0f','synthetic PCM audio; session save/reopen, mixer gain and audio conversion'),
 'cad':('cadcraft','0.7.0','fc4e98315a8d771b5ab832f0ade0b5e7b106df7f','editable DXF geometry; exact coordinates/radius after reopen and SVG/PDF/PNG export'),
}

def pinned_cli_version(app, output, expected_name, expected_version, source_commit):
 """Normalize only the exact pinned PDF footer; retain strict CLI identity checks."""
 if not isinstance(output,str) or len(output)>4096 or app not in set(APPS)|{'word','grid','deck'}:return None
 if app=='pdf':
  stem,version,commit,_=APPS['pdf']
  if (expected_name,expected_version,source_commit)!=(stem+'-cli',version,commit):return None
  first=expected_name+' '+expected_version
  # Original pdfcraft 9931329b main.rs::version() and engine/src/links.rs.
  # Every line/link is required. Arbitrary footers, extra lines and credits from
  # another source pin must not be treated as an acceptable native identity.
  original=(first+'\nDiscord: https://discord.gg/artcraft  (help and feedback)\n'
            'Web:     https://getartcraft.com/apps/pdfcraft\n'
            'Source:  https://github.com/storytold/pdfcraft\n')
  return first if output.replace('\r\n','\n')==original else None
 candidate=output.strip()
 expected=re.escape(expected_name)+' '+re.escape(expected_version)+r'(?: \([0-9a-f]+\))?'
 return candidate if re.fullmatch(expected,candidate) is not None else None

def compact(value):
 return json.dumps(value,ensure_ascii=False,separators=(',',':'))

def png_bytes(width=64,height=48):
 """A deterministic, fully opaque RGBA gradient, encoded without external tools."""
 def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
 raw=b''.join(b'\0'+bytes(v for x in range(width) for v in (20+x*170//max(1,width-1),30+y*150//max(1,height-1),70,255)) for y in range(height))
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')

def decode_png(data):
 """Check PNG CRC/deflate and decode noninterlaced 8/16-bit gray/RGB/RGBA.

 Returns real RGBA pixels, so a file signature or blank image cannot pass an
 editing/pixel assertion. Unsupported encodings fail explicitly.
 """
 if data[:8]!=b'\x89PNG\r\n\x1a\n':raise AssertionError('Invalid PNG signature')
 offset=8;compressed=bytearray();header=None;ended=False
 while offset<len(data):
  if offset+12>len(data):raise AssertionError('Truncated PNG chunk')
  length=struct.unpack_from('>I',data,offset)[0];kind=data[offset+4:offset+8];end=offset+12+length
  if end>len(data):raise AssertionError('Truncated PNG chunk payload')
  body=data[offset+8:offset+8+length]
  if zlib.crc32(kind+body)&0xffffffff!=struct.unpack_from('>I',data,end-4)[0]:raise AssertionError('PNG CRC mismatch')
  if kind==b'IHDR':
   if header is not None or length!=13:raise AssertionError('Invalid PNG header')
   header=struct.unpack('>IIBBBBB',body)
  elif kind==b'IDAT':compressed.extend(body)
  elif kind==b'IEND':ended=True;break
  offset=end
 if not ended or header is None:raise AssertionError('Incomplete PNG')
 width,height,depth,color,compression,filter_method,interlace=header
 if not(0<width<=16384 and 0<height<=16384 and width*height<=16_000_000) or compression or filter_method or interlace or depth not in (8,16) or color not in (0,2,4,6):
  raise AssertionError('Unsupported or excessive PNG encoding: '+str(header))
 channels={0:1,2:3,4:2,6:4}[color];bpp=channels*(depth//8);stride=width*bpp;expected=(stride+1)*height
 decompressor=zlib.decompressobj();raw=decompressor.decompress(bytes(compressed),expected+1)
 if len(raw)!=expected or not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:raise AssertionError('PNG deflate length mismatch')
 previous=bytearray(stride);pixels=bytearray();position=0
 for _ in range(height):
  mode=raw[position];position+=1;row=bytearray(raw[position:position+stride]);position+=stride
  if mode>4:raise AssertionError('Invalid PNG row filter')
  for i in range(stride):
   a=row[i-bpp] if i>=bpp else 0;b=previous[i];c=previous[i-bpp] if i>=bpp else 0
   if mode==1:predict=a
   elif mode==2:predict=b
   elif mode==3:predict=(a+b)//2
   elif mode==4:
    p=a+b-c;distances=(abs(p-a),abs(p-b),abs(p-c));predict=(a,b,c)[distances.index(min(distances))]
   else:predict=0
   row[i]=(row[i]+predict)&255
  for x in range(width):
   values=[row[x*bpp+c*(depth//8)] for c in range(channels)]
   if color==0:values=[values[0]]*3+[255]
   elif color==2:values+=[255]
   elif color==4:values=[values[0]]*3+[values[1]]
   pixels.extend(values)
  previous=row
 return {'width':width,'height':height,'pixels':bytes(pixels)}

def json_lines(text):
 rows=[]
 for line in text.splitlines():
  if line.strip():rows.append(json.loads(line))
 return rows

def decode_wav(data):
 """Read actual PCM/float RIFF audio, including 24-bit native bounce output."""
 if data[:4]!=b'RIFF' or data[8:12]!=b'WAVE':raise AssertionError('Invalid RIFF/WAVE signature')
 if len(data)<12 or struct.unpack_from('<I',data,4)[0]+8!=len(data):raise AssertionError('WAVE container length mismatch')
 position=12;fmt=None;audio=None
 while position+8<=len(data):
  kind=data[position:position+4];size=struct.unpack_from('<I',data,position+4)[0];body=data[position+8:position+8+size]
  if len(body)!=size:raise AssertionError('Truncated WAVE chunk')
  if kind==b'fmt ':fmt=body
  elif kind==b'data':audio=body
  position+=8+size+(size%2)
 if fmt is None or len(fmt)<16 or audio is None:raise AssertionError('Missing WAVE format/audio')
 encoding,channels,rate,byte_rate,alignment,bits=struct.unpack_from('<HHIIHH',fmt)
 if encoding==0xfffe and len(fmt)>=40:encoding=struct.unpack_from('<H',fmt,24)[0]
 if encoding not in (1,3) or bits not in (16,24,32) or not(0<channels<=8) or rate<=0 or alignment!=channels*(bits//8) or byte_rate!=rate*alignment or len(audio)%alignment:
  raise AssertionError('Unsupported or inconsistent WAVE format')
 if encoding==3 and bits!=32:raise AssertionError('Unsupported float WAVE precision')
 samples=[]
 for offset in range(0,len(audio),bits//8):
  if encoding==3:value=struct.unpack_from('<f',audio,offset)[0]
  else:value=int.from_bytes(audio[offset:offset+bits//8],'little',signed=True)/(2**(bits-1))
  if not math.isfinite(value):raise AssertionError('Non-finite WAVE sample')
  samples.append(value)
 return {'rate':rate,'channels':channels,'frames':len(audio)//alignment,'bits':bits,'rms':math.sqrt(sum(x*x for x in samples)/max(1,len(samples))),'samples':samples}

def inspect_pdf(data):
 """Count actual page dictionaries, including Flate-compressed object streams.

 This covers the native writers used by these scenarios. Unsupported object
 stream filters fail instead of silently treating an unparsed file as a pass.
 """
 if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-2048:]:raise AssertionError('Incomplete PDF header/EOF')
 markers=list(re.finditer(rb'startxref\s+(\d+)\s+%%EOF',data))
 if not markers:raise AssertionError('Missing PDF cross-reference locator')
 offset=int(markers[-1][1])
 if offset>=len(data) or not (data[offset:].startswith(b'xref') or re.match(rb'\d+\s+\d+\s+obj\b',data[offset:])):raise AssertionError('Invalid PDF cross-reference offset')
 pages=len(re.findall(rb'/Type\s*/Page\b',data));streams=0
 for obj in re.finditer(rb'\d+\s+\d+\s+obj\b(.*?)endobj',data,re.S):
  body=obj[1]
  if not re.search(rb'/Type\s*/ObjStm\b',body):continue
  streams+=1
  if not re.search(rb'/Filter\s*(?:\[\s*)?/FlateDecode\b',body):raise AssertionError('Unsupported PDF object-stream filter')
  first=re.search(rb'/First\s+(\d+)',body);count=re.search(rb'/N\s+(\d+)',body)
  stream=re.search(rb'\bstream\r?\n(.*?)\r?\nendstream',body,re.S)
  if first is None or count is None or stream is None:raise AssertionError('Invalid PDF object stream')
  decoder=zlib.decompressobj();decoded=decoder.decompress(stream[1],16_000_001)
  if len(decoded)>16_000_000 or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:raise AssertionError('Invalid or excessive PDF object stream')
  start=int(first[1]);objects=int(count[1])
  if start>len(decoded) or len(decoded[:start].split())!=objects*2:raise AssertionError('Invalid PDF compressed-object index')
  pages+=len(re.findall(rb'/Type\s*/Page\b',decoded[start:]))
 return {'pageObjects':pages,'objectStreams':streams,'xrefOffset':offset}

def dxf_entities(text):
 """Parse ASCII DXF group pairs independently of the application inspector."""
 lines=text.splitlines()
 if len(lines)%2:raise AssertionError('Unpaired DXF group')
 pairs=[(int(lines[i].strip()),lines[i+1].strip()) for i in range(0,len(lines),2)]
 if not pairs or pairs[-1]!=(0,'EOF'):raise AssertionError('Incomplete DXF EOF')
 records=[];active=False;current=None
 for index,(code,value) in enumerate(pairs):
  if code==0 and value=='SECTION':
   active=index+1<len(pairs) and pairs[index+1]==(2,'ENTITIES');continue
  if code==0 and value=='ENDSEC':
   if current is not None:records.append(current);current=None
   active=False
  if not active:continue
  if code==0:
   if current is not None:records.append(current)
   current={'type':value,'groups':{}}
  elif current is not None:current['groups'].setdefault(code,[]).append(value)
 return records

class Smoke:
 def __init__(self,app,cli,out):
  self.app=app;self.cli=cli;self.out=out;self.steps=[];self.checks=[]
  self.env=os.environ.copy()
  for stem,_,_,_ in APPS.values():self.env[stem.upper()+'_CONFIG_DIR']=str(out/'.profile'/stem)
  self.env['SOUNDCRAFT_NO_PREFS']='1'
 def call(self,label,args,input=None):
  if not re.fullmatch(r'[a-zA-Z0-9_-]+',label):raise ValueError('Unsafe step label')
  args=list(map(str,args));started=time.monotonic()
  try:
   process=subprocess.run([str(self.cli),*args],input=input,capture_output=True,text=True,encoding='utf-8',errors='replace',env=self.env,cwd=self.out,timeout=180)
  except subprocess.TimeoutExpired as error:
   stdout=error.stdout or '';stderr=error.stderr or ''
   if isinstance(stdout,bytes):stdout=stdout.decode('utf-8','replace')
   if isinstance(stderr,bytes):stderr=stderr.decode('utf-8','replace')
   self._record(label,args,stdout,stderr,None,started)
   raise AssertionError(label+' exceeded 180 seconds') from error
  self._record(label,args,process.stdout,process.stderr,process.returncode,started)
  if process.returncode:raise AssertionError(label+' failed with exit '+str(process.returncode)+': '+process.stderr[-2000:])
  return process.stdout
 def _record(self,label,args,stdout,stderr,code,started):
  for kind,value in [('stdout',stdout),('stderr',stderr)]:
   (self.out/(label+'.'+kind+'.txt')).write_text(value,encoding='utf-8')
  self.steps.append({'label':label,'args':args,'exitCode':code,'elapsedSeconds':round(time.monotonic()-started,3),'stdout':label+'.stdout.txt','stderr':label+'.stderr.txt'})
 def json(self,label,args,input=None):return json.loads(self.call(label,args,input))
 def check(self,name,condition,detail=None):
  self.checks.append({'name':name,'passed':bool(condition),'detail':detail})
  if not condition:raise AssertionError(name+': '+str(detail))
 def png(self,path):
  image=decode_png(path.read_bytes());self.check(path.name+' PNG CRC, deflate and pixels',True,{'width':image['width'],'height':image['height']});return image
 def pdf(self,path,min_pages=1):
  result=inspect_pdf(path.read_bytes());self.check(path.name+' PDF structure and actual pages',result['pageObjects']>=min_pages,{**result,'minimum':min_pages})
 def separate(self,label,commands,source=None,exports=(),new=None):
  args=['run']
  if self.app=='photo':
   if source:args.append(source)
   if new is not None:args+=['--new',compact(new)]
  elif source:args+=['--in',source]
  for command,params in commands:args+=['--cmd',command,'--params',compact(params)]
  if self.app=='photo':
   if len(exports)!=1:raise ValueError('Photo requires one --out per run')
   args+=['--out',exports[0]]
  else:
   for path in exports:args+=['--export',path]
  rows=json_lines(self.call(label,args))
  for row in rows:
   if row.get('ok') is False or 'error' in row:raise AssertionError('CLI reported a failed command: '+compact(row))
  return rows

def last_result(rows,name):return next(row['result'] for row in reversed(rows) if row.get('command')==name or row.get('id')==name)

def photo(s):
 source=s.out/'gradient.png';source.write_bytes(png_bytes());original=decode_png(source.read_bytes())
 native=s.out/'lossless.pcraft';roundtrip=s.out/'roundtrip.png'
 s.call('01-import-native',['convert',source,native]);s.call('02-reopen-lossless',['convert',native,roundtrip])
 reopened=s.png(roundtrip);s.check('PNG native PNG retains every RGBA pixel',original==reopened)
 layered=s.out/'layered.pcraft'
 s.separate('03-paint-layers',[('layer.new.layer',{'name':'KIO Ink'}),('paint.stroke',{'points':[[5,5,1],[35,20,1]],'size':6,'color':'#00ff00'}),('document.inspect',{})],exports=[layered],new={'width':64,'height':48,'name':'KIO Synthetic'})
 info=s.json('04-reopen-layers',['info',layered,'--compact']);names=[row['name'] for row in info['layers']]
 s.check('Native document retains canvas and distinct layers',info['width']==64 and info['height']==48 and names==['KIO Ink','Background'],names)
 painted=s.out/'painted.png';s.call('05-render-native',['convert',layered,painted]);image=s.png(painted);pixels=image['pixels']
 s.check('Native paint stroke renders green pixels',sum(pixels[i+1]>pixels[i]+80 and pixels[i+1]>pixels[i+2]+80 for i in range(0,len(pixels),4))>20)
 second=s.out/'second.pcraft';s.separate('06-edit-reopened',[('layer.new.layer',{'name':'Reopened QA'})],source=layered,exports=[second])
 info=s.json('07-second-reopen',['info',second,'--compact']);s.check('Further native edits survive a second save',[r['name'] for r in info['layers']]==['Reopened QA','KIO Ink','Background'])

def vector(s):
 native=s.out/'drawing.vectorcraft';svg=s.out/'drawing.svg';png=s.out/'drawing.png';pdf=s.out/'drawing.pdf'
 s.separate('01-create-vectors',[('file.new',{'width':200,'height':100}),('shape.ellipse',{'x':10,'y':10,'width':80,'height':60}),('paint.setFill',{'color':'#3366ff'})],exports=[native,svg,png,pdf])
 rows=s.separate('02-reopen-edit',[('shape.rectangle',{'x':120,'y':20,'width':40,'height':30}),('paint.setFill',{'color':'#ff3300'}),('document.inspect',{})],source=native,exports=[s.out/'second.vectorcraft',s.out/'second.svg'])
 state=last_result(rows,'document.inspect');s.check('Native artboard size retained',state['artboards'][0]['width']==200 and state['artboards'][0]['height']==100,state['artboards'][0])
 s.separate('03-second-reopen',[('document.inspect',{})],source=s.out/'second.vectorcraft',exports=[s.out/'roundtrip.svg'])
 for path in [svg,s.out/'second.svg',s.out/'roundtrip.svg']:
  tree=ET.fromstring(path.read_text());s.check(path.name+' SVG root',tree.tag.split('}')[-1]=='svg')
  s.check(path.name+' original fill retained','3366ff' in path.read_text().lower())
 s.check('SVG retains newly added editable shape','ff3300' in (s.out/'roundtrip.svg').read_text().lower())
 image=s.png(png);s.check('Vector raster has expected dimensions',image['width']==200 and image['height']==100)
 s.check('Vector raster contains visible blue artwork',any(image['pixels'][i+2]>image['pixels'][i]+80 for i in range(0,len(image['pixels']),4)))
 s.pdf(pdf)
 s.call('04-import-exported-svg',['convert',s.out/'roundtrip.svg',s.out/'from-svg.vectorcraft'])
 s.separate('05-svg-native-reopen',[('document.inspect',{})],source=s.out/'from-svg.vectorcraft',exports=[s.out/'from-svg.png']);s.png(s.out/'from-svg.png')

def film(s):
 project=s.out/'timeline.fcproj'
 def edit(label,command,params,first=False):
  args=['--data-dir',s.out/'.profile','--compact']
  args+=['--save-as',project] if first else ['--project',project,'--save']
  return s.json(label,[*args,'exec',command,compact(params)])
 edit('01-new-sequence','file.newSequence',{'name':'KIO QA Sequence','width':160,'height':96,'fps':24,'video':1,'audio':0},True)
 item=edit('02-new-matte','file.newColorMatte',{'color':'#ff0000','seconds':0.5,'width':160,'height':96})['item']
 edit('03-place-matte','timeline.place',{'item':item,'track':'V1','seconds':0})
 edit('04-razor','timeline.razor',{'seconds':0.25,'track':'V1'})
 state=s.json('05-reopen-inspect',['--data-dir',s.out/'.profile','--project',project,'inspect','sequence','--compact']);clips=state['video'][0]['items']
 s.check('Native timeline retains razor edit',len(clips)==2 and all(row['durationFrames']==6 for row in clips),clips)
 s.check('Razor preserves source continuity and total duration',clips[0]['end']==clips[1]['start'] and clips[1]['sourceIn']==clips[0]['sourceOut'] and clips[1]['endFrame']==12,clips)
 edit('06-edit-reopened-matte','project.matteColor',{'item':item,'color':'#0000ff'})
 frame=s.out/'frame.png';s.call('07-render-reopened',['--data-dir',s.out/'.profile','--project',project,'render','--seconds','0.125','--out',frame])
 image=s.png(frame);s.check('Reopened edited matte renders blue',image['width']==160 and image['height']==96 and image['pixels'][:3]==b'\0\0\xff',list(image['pixels'][:4]))
 movie=s.out/'synthetic.mp4';s.call('08-encode-video',['--data-dir',s.out/'.profile','--project',project,'export',movie,'--start','0','--end','0.5','--no-audio','--gpu-rendering','off'])
 data=movie.read_bytes();s.check('Encoded MP4 contains actual H.264 sample tables/media',b'ftyp' in data[:128] and b'moov' in data and b'mdat' in data and b'avc1' in data and len(data)>256)
 probe=s.json('09-reopen-encoded-video',['--data-dir',s.out/'.profile','probe',movie]);s.check('Native decoder reopens encoded video',isinstance(probe.get('video'),dict),probe)

def effect(s):
 project=s.out/'animation.ecproj'
 s.json('01-new-comp',['exec','comp.new','--params',compact({'name':'KIO QA','width':160,'height':96,'duration':2}),'--empty','--save-as',project,'--json'])
 s.json('02-new-solid',['exec','layer.newSolid',compact({'name':'Blue','color':'#0000ff','width':160,'height':96}),project,'--save','--json'])
 for label,time_value,position in [('03-key-start',0,[0,48]),('04-key-end',2,[160,48])]:
  s.json(label,['set','KIO QA','Blue','transform/position',compact(position),'--time',time_value,project,'--save','--json'])
 readback=s.json('05-reopen-interpolation',['get','KIO QA','Blue','transform/position','--time','1',project,'--json'])
 s.check('Native composition retains two animation keys',len(readback['keys'])==2,readback)
 s.check('Native evaluator interpolates midpoint',abs(readback['value'][0]-80)<1 and abs(readback['value'][1]-48)<1,readback['value'])
 frame=s.out/'midpoint.png';s.json('06-render-keyframe',['render-frame',project,'--comp','KIO QA','--time','1','--out',frame,'--json']);image=s.png(frame)
 s.check('Reopened animation renders blue solid at midpoint',image['width']==160 and image['height']==96 and sum(image['pixels'][i+2]>image['pixels'][i]+100 for i in range(0,len(image['pixels']),4))>100)

def design(s):
 native=s.out/'layout.designcraft';idml=s.out/'layout.idml';pdf=s.out/'layout.pdf';png=s.out/'layout.png';epub=s.out/'layout.epub'
 commands=[('file.new',{'pages':1}),('frame.create',{'rect':[36,36,300,180],'content':'text','text':'KIO Synthetic Layout'}),('story.get',{'story':'$1.story'}),('document.inspect',{})]
 script='\n'.join(name+' '+compact(params) for name,params in commands)+'\n'
 result=s.json('01-create-layout',['script','-','--save',native,'--export',idml,'--export',pdf,'--export',png,'--export',epub],input=script)
 s.check('Created layout contains actual text story',result['results'][2]['text']=='KIO Synthetic Layout',result['results'][2])
 for label,source in [('02-native-reopen',native),('03-idml-reimport',idml)]:
  inspection=s.json(label+'-inspect',['script','-','--in',source],input='document.inspect {}\n')
  story=inspection['results'][0]['stories'][0]['id']
  reopened=s.json(label,['script','-','--in',source,'--save',s.out/(label+'.designcraft')],input='story.get '+compact({'story':story})+'\n')
  s.check(label+' retains editable story text',reopened['results'][0]['text']=='KIO Synthetic Layout',reopened['results'][0])
 import zipfile
 for file,required in [(idml,['mimetype','designmap.xml']),(epub,['mimetype','META-INF/container.xml'])]:
  with zipfile.ZipFile(file) as archive:
   s.check(file.name+' complete valid ZIP',archive.testzip() is None and all(name in archive.namelist() for name in required))
   text=b'\n'.join(archive.read(name) for name in archive.namelist() if name.endswith(('.xml','.xhtml','.html')))
   s.check(file.name+' physically serializes story text',b'KIO Synthetic Layout' in text)
 s.pdf(pdf);image=s.png(png);s.check('Text layout raster contains visible glyph pixels',len(set(image['pixels'][0::4]))>1)

def ui(s):
 native=s.out/'interface.figcraft';commands=[{'command':'frame.create','params':{'x':0,'y':0,'width':100,'height':50,'name':'KIO Red','props':{'fill':'#ff0000'}}},{'command':'frame.create','params':{'x':200,'y':0,'width':30,'height':30,'name':'KIO Second'}}]
 script=s.out/'create.jsonl';script.write_text('\n'.join(compact(row) for row in commands)+'\n',encoding='utf-8')
 rows=json_lines(s.call('01-create-frames',['run',script,'--out',native]));s.check('UI commands actually execute',len(rows)==2 and all(row.get('ok') is True for row in rows))
 info=s.json('02-native-reopen',['info','--json',native]);frames=info['pages'][0]['frames'];s.check('Native UI retains both named frames',{row['name'] for row in frames}=={'KIO Red','KIO Second'},frames)
 export=s.out/'frames';s.call('03-export-frames',['export',native,'-o',export,'--scale','2']);image=s.png(export/'KIO Red.png');s.png(export/'KIO Second.png')
 s.check('UI frame export applies scale',image['width']==200 and image['height']==100)
 s.check('UI original frame fill survives native reopen',image['pixels'][:3]==b'\xff\0\0',list(image['pixels'][:4]))
 svg=s.out/'second.svg';s.call('04-export-editable-svg',['export',native,'-o',svg,'--node','KIO Second']);s.check('UI export is parseable SVG',ET.fromstring(svg.read_text()).tag.split('}')[-1]=='svg')
 json_file=s.out/'interface.json';second=s.out/'roundtrip.figcraft'
 s.call('05-convert-json',['convert',native,json_file]);s.call('06-json-native',['convert',json_file,second]);reopened=s.json('07-json-reopen',['info','--json',second]);s.check('UI JSON/native conversion retains frame names',{row['name'] for row in reopened['pages'][0]['frames']}=={'KIO Red','KIO Second'})

def sound(s):
 original=s.out/'tone.wav';rate=48000;frames=12000
 with wave.open(str(original),'wb') as file:
  file.setparams((1,2,rate,frames,'NONE','not compressed'))
  file.writeframes(b''.join(struct.pack('<h',round(12000*math.sin(2*math.pi*440*i/rate))) for i in range(frames)))
 original_sha=hashlib.sha256(original.read_bytes()).hexdigest()
 session=s.out/'synthetic.scraft';baseline=s.out/'baseline.wav';quiet=s.out/'quiet.wav';again=s.out/'reopened.wav'
 def run(label,commands,source=None,save=None,bounce=None):
  args=['run']
  if source:args+=['--in',source]
  for name,params in commands:args+=['--cmd',name+'='+compact(params)]
  if save:args+=['--save',save]
  if bounce:args+=['--bounce',bounce,'--start','0','--end','0.25']
  text=s.call(label,args);results={}
  for line in text.splitlines():
   if ': ' in line:
    command,value=line.split(': ',1)
    if command in {name for name,_ in commands}:results[command]=json.loads(value)
  return results
 info=run('01-import-create-session',[('session.new',{'name':'KIO QA','sample_rate':rate,'bit_depth':24}),('file.import_audio',{'path':str(original)}),('session.inspect',{})],save=session,bounce=baseline)['session.inspect']
 s.check('Sound imports real PCM into a native session',info['sample_rate']==rate and len(info['tracks'])==1 and len(info['tracks'][0]['clips'])==1 and info['sources'][0]['loaded'] is True,info)
 track=info['tracks'][0]['id'];second=s.out/'edited.scraft'
 run('02-reopen-set-gain',[('mix.volume',{'tracks':[track],'db':-6})],source=session,save=second,bounce=quiet)
 info=run('03-reopen-retained-gain',[('session.inspect',{})],source=second,bounce=again)['session.inspect']
 s.check('Sound gain/session media survive save and reopen',info['tracks'][0]['volume_db']==-6 and info['sources'][0]['loaded'] is True,info['tracks'][0])
 a,b,c=[decode_wav(path.read_bytes()) for path in (baseline,quiet,again)]
 s.check('Sound native bounce retains duration/sample rate',all(x['rate']==rate and abs(x['frames']-frames)<=1 for x in (a,b,c)))
 ratio=b['rms']/max(a['rms'],1e-20);s.check('Mixer -6 dB produces the expected actual waveform gain',0.47<ratio<0.54,{'rmsRatio':ratio,'expected':10**(-6/20)})
 s.check('Reopened native audio renders the retained mix',abs(c['rms']-b['rms'])<0.0001 and c['rms']>0.01)
 flac=s.out/'tone.flac';decoded=s.out/'flac-roundtrip.wav'
 s.call('04-export-flac',['convert',original,flac,'--bit-depth','16']);s.check('Actual FLAC container export',flac.read_bytes().startswith(b'fLaC'))
 s.call('05-reopen-flac',['convert',flac,decoded,'--bit-depth','16']);d=decode_wav(decoded.read_bytes());input_audio=decode_wav(original.read_bytes())
 s.check('FLAC reimport preserves real audio samples and duration',d['rate']==rate and d['frames']==frames and abs(d['rms']-input_audio['rms'])<0.0001)
 s.check('Sound original synthetic input unchanged',hashlib.sha256(original.read_bytes()).hexdigest()==original_sha)

def cad(s):
 native=s.out/'drawing.dxf';second=s.out/'edited.dxf'
 s.call('01-create-native-drawing',['run','--metric','--cmd','line '+compact({'points':[[0,0],[3,4]]}),'--cmd','circle '+compact({'center':[10,10],'radius':2.5}),'--save',native])
 first=s.json('02-reopen-dxf',['info',native]);s.check('CAD native DXF retains distinct entity kinds',first['counts'].get('Line')==1 and first['counts'].get('Circle')==1,first['counts'])
 s.call('03-edit-reopened',['run',native,'--cmd','ellipse '+compact({'center':[20,10],'major':[4,0],'ratio':0.5}),'--save',second])
 state=s.json('04-reopen-edited',['info',second]);s.check('Further editable CAD geometry survives save',state['counts'].get('Line')==1 and state['counts'].get('Circle')==1 and state['counts'].get('Ellipse')==1,state['counts'])
 records=dxf_entities(second.read_text());line=next(r['groups'] for r in records if r['type']=='LINE');circle=next(r['groups'] for r in records if r['type']=='CIRCLE');ellipse=next(r['groups'] for r in records if r['type']=='ELLIPSE')
 s.check('Independent DXF readback retains exact line coordinates',[float(line[k][0]) for k in (10,20,11,21)]==[0,0,3,4],line)
 s.check('Independent DXF readback retains circle and ellipse dimensions',[float(circle[k][0]) for k in (10,20,40)]==[10,10,2.5] and float(ellipse[40][0])==0.5)
 distance=s.json('05-distance-calculation',['run',second,'--cmd','dist '+compact({'p1':[0,0],'p2':[3,4]})]);s.check('Native CAD distance calculation',distance['distance']==5 and distance['dx']==3 and distance['dy']==4,distance)
 area=s.json('06-area-calculation',['run',second,'--cmd','area '+compact({'points':[[0,0],[4,0],[4,3]]})]);s.check('Native CAD polygon area/perimeter calculation',abs(area['area']-6)<1e-9 and abs(area['perimeter']-12)<1e-9,area)
 for extension in ('svg','png','pdf'):
  file=s.out/('drawing.'+extension);s.call('07-export-'+extension,['convert',second,file])
  if extension=='svg':s.check('CAD SVG is valid vector XML',ET.fromstring(file.read_text()).tag.split('}')[-1]=='svg')
  elif extension=='pdf':s.pdf(file)
  else:
   image=s.png(file);s.check('CAD raster exports actual nonblank geometry',image['width']==2400 and image['height']==1600 and len(set(image['pixels'][0::4]))>1)

def plan(app):
 stem,version,commit,scope=APPS[app]
 return {'app':app,'status':'not_run','upstreamRepository':'https://github.com/storytold/'+stem,'commit':commit,'version':version,'scope':scope,'contract':'https://github.com/storytold/'+stem+'/blob/'+commit+'/apps/'+stem+'-cli/src/main.rs','requirements':'Already built matching full native CLI; Python standard library; no model downloads or external encoder.'}

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--app',choices=sorted(APPS),required=True);parser.add_argument('--cli',type=Path);parser.add_argument('--output',type=Path);parser.add_argument('--plan',action='store_true');args=parser.parse_args(argv)
 if args.plan:print(json.dumps(plan(args.app),ensure_ascii=False,indent=2));return 0
 if args.cli is None or args.output is None:parser.error('--cli ABS and --output freshdir are required unless --plan is used')
 if not args.cli.is_absolute() or not args.cli.is_file():parser.error('--cli must be an existing absolute native CLI path')
 cli=args.cli.resolve(strict=True);out=args.output.expanduser().absolute()
 if out.is_symlink() or (out.exists() and (not out.is_dir() or any(out.iterdir()))):parser.error('choose a fresh, empty output directory; no previous files are replaced')
 out.mkdir(parents=True,exist_ok=True);out=out.resolve();s=Smoke(args.app,cli,out);error=None
 try:
  raw_version=s.call('00-version',['--version']);stem,want,commit,_=APPS[args.app];prefix='SoundCraft CLI' if args.app=='sound' else stem+'-cli'
  version=pinned_cli_version(args.app,raw_version,prefix,want,commit)
  s.check('Actual pinned native CLI version',version is not None,raw_version)
  if args.app in ('light','pdf'):
   from smoke_craft_documents import light,pdf
   function={'light':light,'pdf':pdf}[args.app]
  else:function=globals()[args.app]
  function(s)
 except Exception as exception:error=str(exception)
 files=[]
 for file in sorted(out.rglob('*')):
  if file.is_file() and not file.is_symlink() and file.name!='report.json':files.append({'name':file.relative_to(out).as_posix(),'bytes':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
 contract={k:v for k,v in plan(args.app).items() if k not in ('app','status')}
 report={'schema':'kio.native-craft-smoke.v1','app':args.app,'status':'failed' if error else 'passed','contract':contract,'cli':str(cli),'cliSha256':hashlib.sha256(cli.read_bytes()).hexdigest(),'checks':s.checks,'steps':s.steps,'files':files,'error':error}
 (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(compact({'app':args.app,'status':report['status'],'checks':len(s.checks),'report':str(out/'report.json'),'error':error}));return 1 if error else 0

if __name__=='__main__':sys.exit(main())
