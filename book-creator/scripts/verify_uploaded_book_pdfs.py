"""Read back only the two repaired private PDFs; print no credentials or signed URLs."""
from pathlib import Path
import hashlib,json,os,urllib.request
SLUGS=('carlyle_critical_miscellaneous_essays_volume_iv','carlyle_past_and_present')
base=os.environ['SUPABASE_URL'].rstrip('/')
key=os.environ['SUPABASE_SERVICE_ROLE_KEY']
results=[]
for slug in SLUGS:
    folder=Path('book-creator/books')/slug
    metadata=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
    local=(folder/metadata['interior_filename']).read_bytes()
    expected=hashlib.sha256(local).hexdigest()
    request=urllib.request.Request(base+'/storage/v1/object/authenticated/book-pdfs/'+slug+'.pdf',headers={'Authorization':'Bearer '+key,'apikey':key,'Cache-Control':'no-cache'})
    with urllib.request.urlopen(request,timeout=90) as response:remote=response.read()
    actual=hashlib.sha256(remote).hexdigest()
    assert remote.startswith(b'%PDF') and actual==expected,(slug,'stored PDF hash mismatch',expected,actual)
    results.append(dict(slug=slug,sha256=actual,bytes=len(remote),matches_repository=True,commit=os.environ['GITHUB_SHA']))
Path('book-pdf-verification.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
print(json.dumps(results))
