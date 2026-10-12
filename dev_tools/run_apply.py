import sys, time
sys.path.insert(0, '/home/user/SnowRunner-Hardmod-Plus/Hard Mode Plus')
import sslpatch as SP, service_patches as SV
DATA = '/tmp/claude-0/-home-user-SnowRunner-Hardmod-Plus/4f10eee7-7669-5080-b6af-5b4cdb4ff33e/scratchpad/data/'
def load(flavor='release'):
    pre, names, blobs = SP.split_bundle(open(DATA + flavor + '.sslbundle', 'rb').read())
    idx = {n: i for i, n in enumerate(names)}
    return pre, names, blobs, idx
def editors(names, blobs, idx):
    return {n: SP.ModEditor(blobs[idx[n]], n) for n in SV.ALL_MODULES}
if __name__ == '__main__':
    flavor = sys.argv[1] if len(sys.argv) > 1 else 'release'
    keys = sys.argv[2].split(',') if len(sys.argv) > 2 else list(SV.KEYS)
    pre, names, blobs, idx = load(flavor)
    ed = editors(names, blobs, idx)
    t = time.time()
    ch = SV.apply(ed, {k: {SV.LOADING_KEY: SV.LOADING_VALUE, SV.LIGHTS_KEY: SV.LIGHTS_DEFAULT}.get(k, True) for k in keys})
    print(flavor, 'changed', sorted(ch), '%.1fs' % (time.time() - t))
    out = list(blobs)
    for n in ch:
        out[idx[n]] = ed[n].blob()
    open(flavor + '_patched.sslbundle', 'wb').write(SP.join_bundle(pre, out))
