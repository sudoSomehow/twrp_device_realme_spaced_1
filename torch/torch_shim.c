/* Recovery-only stdio adapter; never opens the hardware until the UI requests ON. */
typedef unsigned long size_t;
typedef long ssize_t;
typedef void FILE;
extern long syscall(long,...);
extern int ioctl(int,unsigned long,...);
extern int snprintf(char*,size_t,const char*,...);
extern int strcmp(const char*,const char*);
extern int fileno(FILE*);
extern void *dlsym(void*,const char*);
extern int unsetenv(const char*);
extern int *__errno(void);
extern void abort(void);
/* Bionic LP64 pthread_mutex_t: 10 int32_t words, zero-initialized NORMAL. */
static struct { int words[10]; } lock __attribute__((aligned(8)));
_Static_assert(sizeof(lock)==40,"Bionic LP64 mutex ABI mismatch");
extern int pthread_mutex_lock(void*);
extern int pthread_mutex_unlock(void*);
#define SYS_OPENAT 56
#define SYS_CLOSE 57
#define SYS_WRITE 64
#define SYS_READLINKAT 78
#define AT_FDCWD -100
#define FLAGS_RW (2|524288|131072)
#define BRIGHTNESS "/tmp/n50_torch_/flashlight/brightness"
static size_t (*next_fwrite)(const void*,size_t,size_t,FILE*);
#include "torch_control.h"
static struct n50_state state={-1,0};
static int n50_hw_open(void) { return (int)syscall(SYS_OPENAT,AT_FDCWD,"/dev/flashlight",FLAGS_RW,0); }
static int n50_hw_ioctl(int fd,unsigned long req,struct n50_arg *arg) {
    int ret=ioctl(fd,req,arg);
    if(ret<0) n50_log("ioctl failed",(int)(req&255));
    return ret;
}
static void n50_hw_close(int fd) { (void)syscall(SYS_CLOSE,fd); }
static void n50_log(const char *stage,int result) {
    char msg[256];
    int length=snprintf(msg,sizeof(msg),"n50-torch: %s (result=%d, errno=%d)\n",stage,result,*__errno());
    int fd=(int)syscall(SYS_OPENAT,AT_FDCWD,"/tmp/n50-torch.log",1|64|1024|524288|131072,0644);
    if(fd>=0) {
        if(length>0 && length<(int)sizeof(msg)) (void)syscall(SYS_WRITE,fd,msg,(size_t)length);
        (void)syscall(SYS_CLOSE,fd);
    }
}
static int target(FILE *f) {
    char path[64], resolved[256];
    int fd=fileno(f);
    if(fd<0) return 0;
    int n=snprintf(path,sizeof(path),"/proc/self/fd/%d",fd);
    if(n<=0 || n>=(int)sizeof(path)) return 0;
    long length=syscall(SYS_READLINKAT,AT_FDCWD,path,resolved,sizeof(resolved)-1);
    if(length<0 || length>=(long)sizeof(resolved)) return 0;
    resolved[length]=0;
    return strcmp(resolved,BRIGHTNESS)==0;
}
__attribute__((constructor)) static void start(void) {
    next_fwrite=(size_t(*)(const void*,size_t,size_t,FILE*))dlsym((void*)-1L,"fwrite");
    /* Do not propagate this preload to child processes. */
    (void)unsetenv("LD_PRELOAD");
    n50_log("adapter ready; hardware untouched until an ON request",0);
}
__attribute__((destructor)) static void stop(void) {
    pthread_mutex_lock(&lock);
    (void)n50_off(&state);
    pthread_mutex_unlock(&lock);
}
__attribute__((visibility("default"))) size_t fwrite(const void *buf,size_t size,size_t count,FILE *f) {
    if(!next_fwrite) return 0;
    if(!size || !count || size>~(size_t)0/count || !target(f)) return next_fwrite(buf,size,count,f);
    size_t bytes=size*count;
    const unsigned char *p=buf;
    int valid=buf && bytes<=8 && (p[0]=='0'||p[0]=='1');
    for(size_t i=1;valid && i<bytes;i++) if(p[i]!='\n' && p[i]!='\r' && p[i]!=' ' && p[i]!='\t') valid=0;
    pthread_mutex_lock(&lock);
    int ret=!valid ? -1 : (p[0]=='1' ? n50_on(&state) : n50_off(&state));
    if(!valid) (void)n50_off(&state);
    size_t written;
    if(ret<0) {
        written=next_fwrite("0",1,1,f); (void)written;
        n50_log("ERROR: command failed/rejected; state file reset to OFF",ret);
        written=0; *__errno()=5;
    } else written=next_fwrite(buf,size,count,f);
    pthread_mutex_unlock(&lock);
    return written;
}
__attribute__((visibility("default"))) size_t __fwrite_chk(const void *buf,size_t size,size_t count,FILE *f,size_t capacity) {
    if(count && (size>~(size_t)0/count || size*count>capacity)) abort();
    return fwrite(buf,size,count,f);
}
