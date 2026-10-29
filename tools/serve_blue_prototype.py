"""PROTOTYPE: three blue layouts on the existing viewer route; localhost only."""
import argparse,json,pathlib
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from urllib.parse import urlparse

ROOT=pathlib.Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--port',type=int,default=8742)
p.add_argument('--reference-dir',type=pathlib.Path,help='Optional local reference PNG directory; never copied or published')
args=p.parse_args()
cases=json.loads((ROOT/'web/data/original-occ/catalog.json').read_text())['cases']
images={str(c['number']):c['id']+'.png' for c in cases}

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'web'),**kw)
    def do_GET(self):
        route=urlparse(self.path).path
        if route.startswith('/_prototype-reference/'):
            number=route.rsplit('/',1)[-1].removesuffix('.png')
            image=args.reference_dir/images[number] if args.reference_dir and number in images else None
            if image and image.is_file():
                body=image.read_bytes();self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            else:self.send_error(404,'No local reference configured')
            return
        super().do_GET()

print(f'Blue UI prototypes: http://127.0.0.1:{args.port}/?variant=A#series=original&case=36&variant=trim-to_walls-r8',flush=True)
ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
