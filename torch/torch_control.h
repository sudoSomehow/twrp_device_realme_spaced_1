/* Device-specific MTK protocol v2 controller. Tested with a mock backend. */
#ifndef N50_TORCH_CONTROL_H
#define N50_TORCH_CONTROL_H
#define N50_IO(n) (0x80045300UL | (n))
#define N50_DRIVER 0xc004531eUL
#define N50_SCENARIO 0xc00453d7UL
#define N50_READY N50_IO(220)
#define N50_VERSION N50_IO(190)
#define N50_MAX_TORCH 0xc00453e6UL
#define N50_DUTY_COUNT 0xc00453e1UL
#define N50_TIMEOUT N50_IO(100)
#define N50_DUTY N50_IO(110)
#define N50_ONOFF N50_IO(115)
#define N50_TIMEOUT_MS 60000
struct n50_arg { int type_id, ct_id, arg; };
_Static_assert(sizeof(struct n50_arg)==12,"MTK user argument ABI mismatch");
struct n50_state { int fd; int driver; };
static int n50_hw_open(void);
static int n50_hw_ioctl(int fd, unsigned long request, struct n50_arg *arg);
static void n50_hw_close(int fd);
static void n50_log(const char *stage, int result);
static int n50_cmd(struct n50_state *s, unsigned long request, int value, int *out) {
    /* Capture identifies type index 0 / ct index 0 -> userspace IDs 1 / 1. */
    struct n50_arg a={1,1,value};
    int ret=n50_hw_ioctl(s->fd,request,&a);
    if(out) *out=a.arg;
    return ret;
}
static int n50_off(struct n50_state *s) {
    int result=0;
    if(s->fd<0) return 0;
    if(s->driver) {
        if(n50_cmd(s,N50_SCENARIO,2,0)<0) result=-1;
        if(n50_cmd(s,N50_ONOFF,0,0)<0) result=-1;
        if(n50_cmd(s,N50_DRIVER,0,0)<0) result=-1;
    }
    n50_hw_close(s->fd); s->fd=-1; s->driver=0;
    n50_log("OFF: decoupled channel 0, driver released",result);
    return result;
}
static int n50_on(struct n50_state *s) {
    int value=-1, ret;
    if(s->fd>=0 && s->driver) {
        /* Re-ON also works after the kernel's safety timer has expired. */
        if(n50_off(s)<0) return -1;
    }
    s->fd=n50_hw_open();
    if(s->fd<0) { n50_log("ERROR opening /dev/flashlight",s->fd); return -1; }
    if(n50_cmd(s,N50_VERSION,0,0)!=2) goto bad;
    if(n50_cmd(s,N50_READY,0,&value)<0 || value!=1) goto bad;
    if(n50_cmd(s,N50_MAX_TORCH,0,&value)<0 || value<0) goto bad;
    if(n50_cmd(s,N50_DUTY_COUNT,0,&value)<0 || value<=0) goto bad;
    /* Attempted SET_DRIVER may acquire a reference even if init reports error. */
    s->driver=1;
    if(n50_cmd(s,N50_DRIVER,1,0)<0) goto bad;
    if(n50_cmd(s,N50_SCENARIO,2,0)<0) goto bad;
    if(n50_cmd(s,N50_TIMEOUT,N50_TIMEOUT_MS,0)<0) goto bad;
    if(n50_cmd(s,N50_DUTY,0,0)<0) goto bad;
    ret=n50_cmd(s,N50_ONOFF,1,0);
    if(ret<0) goto bad;
    n50_log("ON command accepted: decoupled channel 0, duty 0, 60s safety timer",ret);
    return 0;
bad:
    n50_log("ERROR: ioctl validation/setup failed; requested OFF",-1);
    n50_off(s);
    return -1;
}
#endif
