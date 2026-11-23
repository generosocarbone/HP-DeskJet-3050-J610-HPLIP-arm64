/* Experimental, model-specific LEDM frontend for HP's HPLIP scanner sources. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include "hpmud.h"
#include "ledm.h"

static int valid_uri(const char *uri) {
 const char *prefix="/usb/Deskjet_3050_J610_series?serial=";
 return !strncmp(uri,prefix,strlen(prefix)) && strlen(uri)>strlen(prefix);
}

static int count_options(SANE_Handle h) {
 SANE_Int n=0;
 if (ledm_control_option(h,0,SANE_ACTION_GET_VALUE,&n,NULL) || n<1 || n>64) return 0;
 return n;
}

static int set_option(SANE_Handle h, const char *name, void *value) {
 int count=count_options(h);
 for(int i=1;i<count;++i) {
  const SANE_Option_Descriptor *o=ledm_get_option_descriptor(h,i);
  if(o && o->name && !strcmp(o->name,name))
   return ledm_control_option(h,i,SANE_ACTION_SET_VALUE,value,NULL);
 }
 return SANE_STATUS_UNSUPPORTED;
}

static int choose_dpi(SANE_Handle h, SANE_Int *dpi) {
 int count=count_options(h);
 for(int i=1;i<count;++i) {
  const SANE_Option_Descriptor *o=ledm_get_option_descriptor(h,i);
  if(!o || !o->name || strcmp(o->name,"resolution")) continue;
  if(o->constraint_type==SANE_CONSTRAINT_WORD_LIST) {
   const SANE_Word *v=o->constraint.word_list;
   if(!v || v[0]<1 || v[0]>128) return 1;
   const int preferred[]={150,100,200,300,75};
   for(unsigned j=0;j<sizeof(preferred)/sizeof(*preferred);++j)
    for(int k=1;k<=v[0];++k) if(v[k]==preferred[j]) { *dpi=v[k]; return 0; }
   return 1;
  }
  if(o->constraint_type==SANE_CONSTRAINT_RANGE && o->constraint.range) {
   const SANE_Range *r=o->constraint.range;
   int d=150;
   if(d<r->min) d=r->min;
   if(d>r->max) d=r->max;
   if(r->quant>0) d=r->min+((d-r->min)/r->quant)*r->quant;
   if(d<50 || d>300) return 1;
   *dpi=d; return 0;
  }
  return 1;
 }
 return 1;
}

static int scan_to_pnm(SANE_Handle h,const char *path) {
 SANE_Int dpi=150;
 char mode[]="Color",source[]="Flatbed";
 SANE_Status status;
 SANE_Parameters p;
 FILE *spool=NULL,*out=NULL;
 int started=0,ok=0,fd=-1;
 uint8_t buffer[65536];
 size_t total=0;
 /* Refuse accidental overwrite before starting the mechanism. */
 if (access(path,F_OK)==0) { fputs("Output already exists.\n",stderr); return 1; }
 status=set_option(h,"mode",mode);
 if(status) { fprintf(stderr,"Color mode rejected: %d\n",status); return 1; }
 status=set_option(h,"source",source);
 if(status) { fprintf(stderr,"Flatbed selection rejected: %d\n",status); return 1; }
 if(choose_dpi(h,&dpi)) { fputs("No supported low-resolution scan mode.\n",stderr); return 1; }
 status=set_option(h,"resolution",&dpi);
 if(status) { fprintf(stderr,"Resolution %d dpi rejected: %d\n",dpi,status); return 1; }
 spool=tmpfile();
 if(!spool) { perror("tmpfile"); return 1; }
 status=ledm_start(h);
 if(status) { fprintf(stderr,"Scan start failed: %d\n",status); goto done; }
 started=1;
 status=ledm_get_parameters(h,&p);
 if(status || p.depth!=8 || (p.format!=SANE_FRAME_RGB && p.format!=SANE_FRAME_GRAY) || p.pixels_per_line<=0 || p.pixels_per_line>20000 || p.bytes_per_line<=0 || p.bytes_per_line>60000) {
  fprintf(stderr,"Unsupported raster parameters, status=%d\n",status); goto done;
 }
 size_t rowbytes=(size_t)p.pixels_per_line*(p.format==SANE_FRAME_RGB?3:1);
 if(rowbytes>(size_t)p.bytes_per_line) { fputs("Invalid raster stride.\n",stderr); goto done; }
 time_t start=time(NULL); unsigned empty_reads=0;
 for(;;) {
  SANE_Int got=0;
  status=ledm_read(h,buffer,sizeof(buffer),&got);
  if(got<0 || got>(SANE_Int)sizeof(buffer)) { fputs("Invalid read length.\n",stderr); goto done; }
  if(got) {
   total+=(size_t)got;
   if(total>100u*1024u*1024u || fwrite(buffer,1,(size_t)got,spool)!=(size_t)got) { fputs("Scan exceeds limit or write failed.\n",stderr); goto done; }
   empty_reads=0;
  } else if(++empty_reads>50 && status!=SANE_STATUS_EOF) { fputs("Scanner returned no data.\n",stderr); goto done; }
  if(status==SANE_STATUS_EOF) break;
  if(status!=SANE_STATUS_GOOD) { fprintf(stderr,"Scan read failed: %d\n",status); goto done; }
  if(time(NULL)-start>180) { fputs("Scan exceeded 180 second limit.\n",stderr); goto done; }
 }
 if(!total || total%(size_t)p.bytes_per_line) { fputs("Incomplete raster rows.\n",stderr); goto done; }
 size_t rows=total/(size_t)p.bytes_per_line;
 if(rows>20000) { fputs("Too many raster rows.\n",stderr); goto done; }
 ledm_cancel(h); started=0;
 if(fseek(spool,0,SEEK_SET)) goto done;
 fd=open(path,O_WRONLY|O_CREAT|O_EXCL,0600);
 if(fd<0) { perror("output"); goto done; }
 out=fdopen(fd,"wb");
 if(!out) { close(fd); fd=-1; goto done; }
 fd=-1;
 if(fprintf(out,"%s\n%u %zu\n255\n",p.format==SANE_FRAME_RGB?"P6":"P5",(unsigned)p.pixels_per_line,rows)<0) goto done;
 for(size_t row=0;row<rows;++row) {
  if(fread(buffer,1,(size_t)p.bytes_per_line,spool)!=(size_t)p.bytes_per_line || fwrite(buffer,1,rowbytes,out)!=rowbytes) goto done;
 }
 if(fclose(out)) { out=NULL; goto done; }
 out=NULL; ok=1;
 fprintf(stderr,"Saved %u x %zu pixels at requested %d dpi to %s\n",(unsigned)p.pixels_per_line,rows,dpi,path);
 done:
 if(started) ledm_cancel(h);
 if(spool) fclose(spool);
 if(out) fclose(out);
 if(!ok && fd>=0) close(fd);
 return !ok;
}

int main(int argc,char **argv) {
 if(argc==2 && !strcmp(argv[1],"--self-test")) {
  struct hpmud_model_attributes ma={0};
  int r=hpmud_query_model("hp:/usb/Deskjet_3050_J610_series?serial=offline",&ma);
  printf("model lookup=%d scan-type=%d io-mode=%d\n",r,ma.scantype,ma.mfp_mode);
  return r || ma.scantype!=7;
 }
 int probe=argc==3 && !strcmp(argv[1],"--probe");
 int scan=argc==4 && !strcmp(argv[1],"--scan");
 if(probe || scan) {
  if(!valid_uri(argv[2])) { fputs("Expected exact J610 USB URI without hp:.\n",stderr); return 2; }
  SANE_Handle h=NULL;
  SANE_Status s=ledm_open(argv[2],&h);
  fprintf(stderr,"LEDM open status=%d\n",s);
  if(s) return 1;
  int result=0;
  if(scan) result=scan_to_pnm(h,argv[3]);
  else {
   int count=count_options(h);
   if(!count) result=1;
   for(int n=0;n<count;++n) {
    const SANE_Option_Descriptor *o=ledm_get_option_descriptor(h,n);
    if(!o) { result=1; break; }
    printf("%d: %s\n",n,o->name?o->name:"");
   }
  }
  ledm_close(h); return result;
 }
 puts("Experimental J610 LEDM scanner frontend.\n--self-test: offline model lookup only\n--probe URI: open USB scanner and list options\n--scan URI output.pnm: 150 dpi color flatbed scan (new output file)");
 return argc==1?0:2;
}
