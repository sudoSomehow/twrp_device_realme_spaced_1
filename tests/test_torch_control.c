/* Pure mock test: no hardware/device I/O exists in this executable. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "torch_control.h"
struct call { unsigned long req; int value; };
static struct call calls[64];
static int count,opens,closes,fail_at,protocol=2,ready=1,max_torch=6,duty_count=39;
static int n50_hw_open(void) { opens++; return 99; }
static int n50_hw_ioctl(int fd,unsigned long req,struct n50_arg *a) {
    assert(fd==99);assert(a->type_id==1 && a->ct_id==1);
    calls[count]=(struct call){req,a->arg}; count++;
    if(count==fail_at) return -1;
    if(req==N50_VERSION) return protocol;
    if(req==N50_READY) a->arg=ready;
    if(req==N50_MAX_TORCH) a->arg=max_torch;
    if(req==N50_DUTY_COUNT) a->arg=duty_count;
    return 0;
}
static void n50_hw_close(int fd) { assert(fd==99);closes++; }
static void n50_log(const char *stage,int result) { (void)stage;(void)result; }
static void reset(void) {
    count=opens=closes=fail_at=0;protocol=2;ready=1;max_torch=6;duty_count=39;
    memset(calls,0,sizeof(calls));
}
int main(void) {
    struct n50_state s={-1,0};
    assert(N50_DRIVER==0xc004531eUL && N50_TIMEOUT==0x80045364UL);
    assert(N50_DUTY==0x8004536eUL && N50_ONOFF==0x80045373UL);
    assert(n50_off(&s)==0);assert(opens==0 && count==0);
    reset();assert(n50_on(&s)==0);assert(count==9 && opens==1 && closes==0);
    assert(calls[4].req==N50_DRIVER && calls[4].value==1);
    assert(calls[5].req==N50_SCENARIO && calls[5].value==2);
    assert(calls[6].req==N50_TIMEOUT && calls[6].value==60000);
    assert(calls[7].req==N50_DUTY && calls[7].value==0);
    assert(calls[8].req==N50_ONOFF && calls[8].value==1);
    assert(n50_off(&s)==0);assert(s.fd==-1 && s.driver==0 && closes==1);
    assert(calls[9].req==N50_SCENARIO && calls[9].value==2);
    assert(calls[10].req==N50_ONOFF && calls[10].value==0);
    assert(calls[11].req==N50_DRIVER && calls[11].value==0);
    for(int i=1;i<=9;i++) {
        reset();s=(struct n50_state){-1,0};fail_at=i;
        assert(n50_on(&s)<0);assert(s.fd==-1 && !s.driver && closes==1);
        if(i>=5) {
            assert(calls[count-2].req==N50_ONOFF && calls[count-2].value==0);
            assert(calls[count-1].req==N50_DRIVER && calls[count-1].value==0);
        }
    }
    reset();s=(struct n50_state){-1,0};protocol=1;
    assert(n50_on(&s)<0 && count==1 && closes==1);
    reset();s=(struct n50_state){-1,0};ready=0;
    assert(n50_on(&s)<0 && count==2 && closes==1);
    reset();s=(struct n50_state){-1,0};max_torch=-1;
    assert(n50_on(&s)<0 && count==3 && closes==1);
    reset();s=(struct n50_state){-1,0};duty_count=0;
    assert(n50_on(&s)<0 && count==4 && closes==1);
    reset();s=(struct n50_state){-1,0};assert(n50_on(&s)==0);assert(n50_on(&s)==0);
    assert(opens==2 && closes==1);assert(n50_off(&s)==0 && closes==2);
    puts("PASS: command ordering, 9 setup failures, 4 query refusals, off-at-start and repeated ON cleanup");
    return 0;
}
