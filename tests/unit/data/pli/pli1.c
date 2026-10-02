/* PLI 1.0 library with a veriusertfs table and a boot routine returning it. */
#include <stdio.h>
#include "veriuser.h"
#ifndef usertask
#include "vxl_veriuser.h"   /* Xcelium's veriuser.h lacks s_tfcell */
#endif
#include "acc_user.h"

static int hello_call(int data, int reason) {
    io_printf("PLI1: hello from $hello_pli1\n");
    return 0;
}

s_tfcell veriusertfs[] = {
    { usertask, 0, 0, 0, hello_call, 0, "$hello_pli1", 1 },
    {0}
};

s_tfcell *pli1_boot(void) { return veriusertfs; }
