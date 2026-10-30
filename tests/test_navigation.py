"""Clean addresses must preserve exact case selection and share-link identity."""
import pathlib,shutil,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('node'),'Node is needed for browser-state routing tests')
class NavigationTests(unittest.TestCase):
    def test_clean_navigation_refresh_sharing_and_legacy_links(self):
        module=(ROOT/'web/navigation.js').read_text()
        script='import assert from "node:assert/strict";\n'+module+'''
const base='https://www.goudanx.top/filletbench/';
const legacy=base+'?v=0.5.1#series=original&case=31&variant=body-r7';
const remembered={series:'original',case:'36',variant:'trim-to_walls-r8'};
const entry=initialView(legacy,null,remembered);
assert.equal(entry.case,'31');assert.equal(entry.variant,'body-r7');
let stored=remembered;
const browser={location:{href:legacy},history:{state:{other:'retained'},replaceState(state,title,url){this.state=state;browser.location.href=url;}},localStorage:{setItem(key,value){assert.equal(key,LAST_VIEW_KEY);stored=JSON.parse(value);}}};
rememberView(browser,entry);
assert.equal(browser.location.href,base);assert.equal(browser.history.state.other,'retained');
assert.equal(initialView(base,browser.history.state,null).variant,'body-r7');
assert.equal(initialView(base,null,stored).case,'31');
rememberView(browser,{series:'original',case:36,variant:'trim-long-r8'});
assert.equal(browser.location.href,base);assert.equal(initialView(base,null,stored).variant,'trim-long-r8');
const link=shareViewerURL(browser.location.href,entry);
assert.equal(link,base+'#31/body-r7');assert.equal(routeFromURL(link).variant,'body-r7');
assert.equal(routeFromURL(base+'#case=16&variant=16.part01.ordinary_challenge.r6').explicitSeries,false);
const historyLink=shareViewerURL(base,{series:'comparison',case:16,variant:'16.part01.ordinary_challenge.r6'});
assert.equal(routeFromURL(historyLink).series,'comparison');
rememberView(browser,{series:'comparison',case:16,variant:'16.part01.ordinary_challenge.r6'});
assert.equal(stored.case,'36');assert.equal(initialView(base,browser.history.state,stored).series,'comparison');
assert.equal(initialView(base,null,stored).series,'original');
rememberView(browser,{series:'original',case:32});
assert.equal(initialView(base,null,stored).variant,null);
const unavailable={location:{href:legacy},history:{state:null,replaceState(state,title,url){this.state=state;unavailable.location.href=url;}},get localStorage(){throw new Error('blocked');}};
assert.doesNotThrow(()=>rememberView(unavailable,entry));assert.equal(unavailable.location.href,base);
assert.equal(initialView(base,unavailable.history.state,null).case,'31');
assert.equal(cleanViewerURL(base+'index.html?v=0.5.1#31/body-r7'),base);
assert.equal(normaliseView({series:'unknown',case:31}),null);
assert.equal(normaliseView({series:'original',case:'../31'}),null);
assert.equal(routeFromURL(base+'#36/%broken'),null);
'''
        subprocess.run(['node','--input-type=module','-e',script],check=True,capture_output=True,text=True)

if __name__=='__main__':unittest.main()
