import sys, pip as P
d=open('../data/release.sslbundle','rb').read()
prefix,names,blobs=P.split_bundle(d)
idx={n:i for i,n in enumerate(names)}
def tree(buf, depth=0, maxd=6):
    try:
        fs=P.pb_fields(buf)
    except Exception as e:
        return None
    return fs
def show(buf, ind=0, maxd=8):
    fs=P.pb_fields(buf)
    for f,s,e,v in fs:
        if isinstance(v,int):
            print(' '*ind+'%d: %d'%(f,v))
        else:
            # try nested
            nested=None
            if len(v)>0 and ind<maxd*2:
                try:
                    nf=P.pb_fields(v)
                    if all(x[0]>0 and x[0]<100 for x in nf): nested=nf
                except Exception: pass
            printable = all(32<=c<127 for c in v) and len(v)>0
            if printable and (nested is None or len(v)<40 and v.isascii()):
                print(' '*ind+'%d: %r'%(f,v.decode()))
            elif nested is not None:
                print(' '*ind+'%d: {'%f)
                show(v, ind+2, maxd)
                print(' '*ind+'}')
            else:
                print(' '*ind+'%d: bytes %s'%(f,v.hex()))
m=P.Module(blobs[idx[sys.argv[1]]])
print(m.header.hex())
show(m.body)
