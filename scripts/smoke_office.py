#!/usr/bin/env python3
"""Headless synthetic QA against an explicitly supplied, already built KIO Craft CLI.
No GUI, builds, installs, user documents, network, or remote control commands.
Example: python3 smoke_office.py --app grid --cli /abs/gridcraft-cli --output /abs/qa/grid
"""
import argparse,csv,hashlib,io,json,os,re,struct,subprocess,sys,time,zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

class Smoke:
 def __init__(self,app,cli,out):
  self.app=app;self.cli=cli;self.out=out;self.steps=[];self.checks=[];self.env={**os.environ,app.upper()+'CRAFT_CONFIG_DIR':str(out/'.profile')}
 def call(self,label,args):
  t=time.time();p=subprocess.run([str(self.cli),*map(str,args)],capture_output=True,text=True,env=self.env,timeout=180)
  (self.out/(label+'.stdout.txt')).write_text(p.stdout);(self.out/(label+'.stderr.txt')).write_text(p.stderr)
  self.steps.append({'label':label,'args':list(map(str,args)),'exitCode':p.returncode,'elapsedSeconds':round(time.time()-t,3),'stdout':label+'.stdout.txt','stderr':label+'.stderr.txt'})
  if p.returncode:raise AssertionError(label+' failed: '+p.stderr[-2000:])
  return p.stdout
 def check(self,name,condition,detail=None):
  self.checks.append({'name':name,'passed':bool(condition),'detail':detail})
  if not condition:raise AssertionError(name+': '+str(detail))
 def run(self,label,commands,source=None,save=None):
  args=['run']
  if source:args+=['--in',str(source)]
  for name,params in commands:args+=['--cmd',name+'='+json.dumps(params,ensure_ascii=False,separators=(',',':'))]
  if self.app=='deck':
   args+=['--print']
   if save:args+=['--save',str(save)]
  elif save:args+=['--out',str(save)]
  text=self.call(label,args);rows=[]
  for line in text.splitlines():
   try:
    if self.app=='grid':rows.append(json.loads(line))
    elif ' → ' in line:
     name,value=line.split(' → ',1);rows.append({'command':name,'result':json.loads(value)})
   except ValueError:continue
  return rows
 def result(self,rows,command):return next(x['result'] for x in reversed(rows) if x['command']==command)
 def pdf(self,p,min_pages=1):
  data=p.read_bytes();self.check(p.name+' PDF signature',data.startswith(b'%PDF-'))
  pages=len(re.findall(rb'/Type\s*/Page\b',data));self.check(p.name+' page objects',pages>=min_pages,{'pages':pages,'expectedMinimum':min_pages})
 def png(self,p):
  data=p.read_bytes();self.check(p.name+' PNG signature',data[:8]==b'\x89PNG\r\n\x1a\n');w,h=struct.unpack('>II',data[16:24]);self.check(p.name+' PNG dimensions',w>10 and h>10,{'width':w,'height':h})
 def zip_xml(self,p,required):
  with zipfile.ZipFile(p) as z:
   self.check(p.name+' valid ZIP CRC',z.testzip() is None)
   self.check(p.name+' package parts',all(n in z.namelist() for n in required),required)
   return {n:ET.fromstring(z.read(n)) for n in z.namelist() if n.endswith('.xml')}

def grid(s):
 p=s.out/'synthetic.xlsx';p2=s.out/'roundtrip.xlsx';pdf=s.out/'synthetic.pdf';csvp=s.out/'synthetic.csv'
 commands=[('sheet.rename',{'name':'KIO QA'}),('range.setValues',{'range':'A1','values':[['Month','Revenue','Check'],['Jan',10,'=SUM(B2:B4)'],['Feb',20,'=AVERAGE(B2:B4)'],['Mar',30,'=B2*2+5'],['Total','=SUM(B2:B4)','=IF(B2>5,"yes","no")']]}),('home.bold',{'range':'A1:C1','on':True}),('home.fontSize',{'range':'A1:C1','size':14}),('home.fillColor',{'range':'A1:C1','color':'#003B7A'}),('home.fontColor',{'range':'A1:C1','color':'#FFFFFF'}),('home.numberFormat',{'range':'B2:B5','code':'0.00'}),('insert.chart',{'range':'A1:B4','type':'column','title':'KIO QA Revenue','at':'E2','width':500,'height':300}),('sheet.read',{'range':'A1:C5'}),('file.exportPdf',{'path':str(pdf),'range':'A1:M20','fitToPage':True}),('file.exportCsv',{'path':str(csvp)})]
 rows=s.run('01-create',commands,save=p);values=s.result(rows,'sheet.read')['values'];s.check('in-memory SUM/AVERAGE/arithmetic/IF',values[1][2]==60 and values[2][2]==20 and values[3][2]==25 and values[4][1]==60 and values[4][2]=='yes',values)
 info=json.loads(s.call('02-reopen-info',['info',p,'--json']));s.check('XLSX reopened sheet name',info['sheets'][0]['name']=='KIO QA',info['sheets'][0]['name']);s.check('XLSX reopened chart count',len(info['sheets'][0]['charts'])==1,info['sheets'][0]['charts'])
 rows=s.run('03-reopen-read',[('sheet.read',{'range':'A1:C5'}),('file.exportPdf',{'path':str(s.out/'reopened.pdf'),'range':'A1:M20','fitToPage':True})],source=p,save=p2);s.check('XLSX reopened formula values',s.result(rows,'sheet.read')['values']==values,s.result(rows,'sheet.read'))
 formula=s.call('04-formula-eval',['eval','SUM(B2:B4)+AVERAGE(B2:B4)','--in',p,'--json']);s.check('formula evaluator on reopened XLSX',json.loads(formula)==80,formula.strip())
 s.call('05-reopen-roundtrip',['info',p2,'--json']);s.call('06-upstream-roundtrip-oracle',['check',p,'--json'])
 a=s.zip_xml(p,['[Content_Types].xml','xl/workbook.xml','xl/worksheets/sheet1.xml','xl/styles.xml']);b=s.zip_xml(p2,['[Content_Types].xml','xl/workbook.xml','xl/worksheets/sheet1.xml','xl/styles.xml']);ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
 formulas=[e.text for e in a['xl/worksheets/sheet1.xml'].findall('.//s:f',ns)];s.check('XLSX formulas physically serialized',all(x in formulas for x in ['SUM(B2:B4)','AVERAGE(B2:B4)','B2*2+5','IF(B2>5,"yes","no")']),formulas)
 s.check('XLSX formulas survive second save',formulas==[e.text for e in b['xl/worksheets/sheet1.xml'].findall('.//s:f',ns)])
 styles=a['xl/styles.xml'];cells={e.get('r'):e for e in a['xl/worksheets/sheet1.xml'].findall('.//s:c',ns)};xfs=styles.find('s:cellXfs',ns);fonts=styles.find('s:fonts',ns)
 header=xfs[int(cells['A1'].get('s','0'))];font=fonts[int(header.get('fontId','0'))];number=xfs[int(cells['B2'].get('s','0'))]
 s.check('XLSX applied bold/font size and number format serialized',font.find('s:b',ns) is not None and font.find('s:sz',ns).get('val')=='14' and number.get('numFmtId')=='2',{'headerStyle':header.attrib,'numberStyle':number.attrib})
 s.check('XLSX chart part serialized',any(n.startswith('xl/charts/chart') for n in a))
 s.pdf(pdf);s.pdf(s.out/'reopened.pdf');data=list(csv.reader(io.StringIO(csvp.read_text(encoding='utf-8-sig'))));s.check('CSV header/data/calculated total',data[0][:3]==['Month','Revenue','Check'] and data[1][0]=='Jan' and float(data[4][1])==60,data)

def deck(s):
 p=s.out/'synthetic.pptx';native=s.out/'synthetic.deckcraft';p2=s.out/'roundtrip.pptx';pdf=s.out/'synthetic.pdf';png=s.out/'slide.png'
 commands=[('file.new',{'blank':True}),('slide.new',{'layout':'titleAndContent','title':'KIO QA Opening','body':'Original full native engine\nSynthetic QA only'}),('slide.notes',{'index':0,'text':'KIO QA speaker note preserved'}),('slide.new',{'layout':'titleAndContent','title':'KIO QA Data','body':'Chart and shape support'}),('insert.chart',{'type':'column','rect':[80,180,500,250],'categories':['Jan','Feb','Mar'],'series':[{'name':'Revenue','values':[10,20,30]}]}),('slide.new',{'layout':'titleAndContent','title':'KIO QA Closing','body':'Save, reopen and export'}),('insert.textBox',{'rect':[80,330,500,60],'text':'KIO QA Bold Label'}),('format.bold',{'on':True}),('shape.insert',{'preset':'roundRect','rect':[650,330,150,60],'text':'KIO QA Shape'}),('shape.fill',{'color':'#007FAD'}),('slide.move',{'from':2,'to':1}),('file.properties',{'title':'KIO Synthetic QA','author':'KIO synthetic fixture'}),('file.saveAs',{'path':str(native)}),('file.export',{'path':str(pdf),'format':'pdf','textLayer':True}),('file.export',{'path':str(png),'format':'png','slide':0,'scale':1}),('document.inspect',{})]
 rows=s.run('01-create',commands,save=p);before=s.result(rows,'document.inspect');titles=[x['title'] for x in before['slides']];s.check('synthetic three-slide order',titles==['KIO QA Opening','KIO QA Closing','KIO QA Data'],titles)
 info=json.loads(s.call('02-reopen-info',['info',p]));s.check('PPTX titles/order preserved',[x['title'] for x in info['slides']]==titles,info['slides']);s.check('PPTX speaker notes preserved',info['slides'][0]['notes']=='KIO QA speaker note preserved',info['slides'][0].get('notes'))
 s.run('03-reopen-save',[('file.export',{'path':str(s.out/'reopened.pdf'),'format':'pdf','textLayer':True})],source=p,save=p2)
 nativeinfo=json.loads(s.call('04-native-reopen',['info',native]));s.check('native project order preserved',[x['title'] for x in nativeinfo['slides']]==titles)
 reopened=json.loads(s.call('05-roundtrip-reopen',['info',p2]));s.check('second PPTX order preserved',[x['title'] for x in reopened['slides']]==titles)
 xml=s.zip_xml(p,['[Content_Types].xml','ppt/presentation.xml','ppt/slides/slide1.xml']);s.zip_xml(p2,['[Content_Types].xml','ppt/presentation.xml','ppt/slides/slide1.xml']);a={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','c':'http://schemas.openxmlformats.org/drawingml/2006/chart'}
 s.check('PPTX chart serialized',any(n.startswith('ppt/charts/chart') for n in xml));alltext=[e.text for tree in xml.values() for e in tree.findall('.//a:t',a)];s.check('PPTX text physically serialized','KIO QA Bold Label' in alltext and 'KIO QA Shape' in alltext)
 s.check('PPTX bold serialized',any(e.get('b')=='1' for tree in xml.values() for e in tree.findall('.//a:rPr',a)))
 charttext=[e.text for n,tree in xml.items() if n.startswith('ppt/charts/') for e in tree.findall('.//c:v',a)];s.check('PPTX chart values serialized',all(x in charttext for x in ['10','20','30']),charttext)
 s.pdf(pdf,3);s.pdf(s.out/'reopened.pdf',3);s.png(png)

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--app',choices=['grid','deck'],required=True);parser.add_argument('--cli',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();cli=args.cli.expanduser().resolve(strict=True);out=args.output.expanduser().resolve();out.mkdir(parents=True,exist_ok=True)
 if any(out.glob('*.xlsx')) or any(out.glob('*.pptx')):parser.error('output already contains QA workbook/deck; choose a fresh output directory')
 s=Smoke(args.app,cli,out);error=None
 try:
  s.call('00-version',['--version']);(grid if args.app=='grid' else deck)(s)
 except Exception as e:error=str(e)
 files=[{'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(out.iterdir()) if p.is_file() and p.name!='report.json']
 report={'schema':'kio.native-office-smoke.v1','app':args.app,'status':'failed' if error else 'passed','cli':str(cli),'cliSha256':hashlib.sha256(cli.read_bytes()).hexdigest(),'scope':'synthetic actual full native CLI; no GUI, builds, installs or commercial compatibility assertion','checks':s.checks,'steps':s.steps,'files':files,'error':error};(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'app':args.app,'status':report['status'],'checks':len(s.checks),'report':str(out/'report.json'),'error':error},ensure_ascii=False));return 1 if error else 0
if __name__=='__main__':sys.exit(main())
