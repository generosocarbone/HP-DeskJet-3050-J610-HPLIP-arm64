from pathlib import Path
import subprocess, re
root=Path(__file__).resolve().parent.parent
src=root/'vendor/hplip-3.26.6'; out=root/'build-scanner'; dist=root/'dist-scanner'
(out/'objects').mkdir(parents=True, exist_ok=True); (out/'compat').mkdir(exist_ok=True); dist.mkdir(exist_ok=True)
(out/'compat/malloc.h').write_text('#include <stdlib.h>\n')
(dist/'etc/hp').mkdir(parents=True,exist_ok=True)
(dist/'etc/hp/hplip.conf').write_text('[dirs]\nhome='+str(src)+'\n')
flags=['clang','-arch','arm64','-O2','-std=gnu99','-fcommon','-D_DARWIN_C_SOURCE','-DHAVE_LIBUSB','-DMUDNAME="hpmud"','-DCONFDIR="'+str(dist/'etc/hp')+'"','-Wno-deprecated-declarations','-Wno-incompatible-pointer-types','-include','stdlib.h','-include','unistd.h']
for p in [out/'compat', src/'common',src/'io/hpmud',src/'scan/sane',src/'ip',src,Path('/opt/homebrew/opt/libusb/include/libusb-1.0')]: flags+=['-I',str(p)]
names=['io/hpmud/'+s+'.c' for s in ['hpmud','mlc','model','pml','dot4','musb']]+['common/utils.c']
names+=['scan/sane/'+s+'.c' for s in ['ledm','bb_ledm','http','xml','common','sanei_init_debug']]
names += [str(p.relative_to(src)) for p in sorted((src/'ip').glob('*.c'))]
files=[src/n for n in names]+[root/'scanner/probe.c',root/'scanner/events.c']
objs=[]
for n,p in enumerate(files):
 obj=out/'objects'/f'{n:03d}-{p.stem}.o'
 print('CC',p.relative_to(root),flush=True)
 subprocess.run(flags+['-c',str(p),'-o',str(obj)],check=True)
 objs.append(str(obj))
subprocess.run(['clang','-arch','arm64','-Wl,-dead_strip',*objs,'/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib','-lcups','-framework','CoreFoundation','-o',str(dist/'j610-scanner-probe')],check=True)
print(dist/'j610-scanner-probe')
