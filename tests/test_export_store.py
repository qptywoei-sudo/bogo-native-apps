import copy
import importlib.util
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('store_export',Path(__file__).resolve().parents[1]/'scripts/export_store_catalog.py')
export=importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)

class PublicStoreReleaseGuards(unittest.TestCase):
 def setUp(self):
  self.catalog={'word':{'name':'KIO Word','version':'0.7.0-kio.1','state':'building','downloads':[]}}
  self.tag='word-v0.7.0-kio.1'
 def asset(self,suffix):
  name='KIO-Word-0.7.0-kio.1-'+suffix
  return {'name':name,'digest':'sha256:'+'a'*64,'size':100,'state':'uploaded','browser_download_url':export.PREFIX+self.tag+'/'+name}
 def release(self):
  return {'tag_name':self.tag,'draft':False,'assets':[self.asset('macos-arm64.dmg'),self.asset('macos-arm64.zip'),self.asset('windows-x64.msi'),self.asset('source.zip')]}
 def test_complete_public_assets_have_exact_launchable_platform_feed(self):
  feed=export.collect(self.catalog,[self.release()])
  self.assertEqual([x['kind'] for x in feed['programs'][0]['artifacts']],['dmg','msi'])
  self.assertEqual(len(self.catalog['word']['downloads']),4)
  self.assertEqual(self.catalog['word']['state'],'released')
 def test_draft_other_app_and_missing_full_source_are_not_downloadable(self):
  for change in ('draft','other','source'):
   release=self.release()
   if change=='draft': release['draft']=True
   if change=='other': release['tag_name']='grid-v0.7.0-kio.1'
   if change=='source': release['assets']=release['assets'][:-1]
   catalog=copy.deepcopy(self.catalog)
   self.assertEqual(export.collect(catalog,[release])['programs'],[])
   self.assertEqual(catalog['word']['downloads'],[])
 def test_foreign_url_absent_hash_unfinished_upload_and_duplicate_fail_closed(self):
  for change in ('url','digest','state','duplicate'):
   release=self.release()
   if change=='url': release['assets'][0]['browser_download_url']='https://example.org/bad.dmg'
   if change=='digest': release['assets'][0]['digest']=None
   if change=='state': release['assets'][0]['state']='uploading'
   if change=='duplicate': release['assets'].append(copy.deepcopy(release['assets'][0]))
   with self.subTest(change=change),self.assertRaises(ValueError): export.collect(copy.deepcopy(self.catalog),[release])
 def test_removed_release_clears_stale_downloads(self):
  export.collect(self.catalog,[self.release()])
  self.assertTrue(self.catalog['word']['downloads'])
  self.assertEqual(export.collect(self.catalog,[])['programs'],[])
  self.assertEqual(self.catalog['word']['downloads'],[])
  self.assertNotIn('releaseUrl',self.catalog['word'])

if __name__=='__main__': unittest.main()
