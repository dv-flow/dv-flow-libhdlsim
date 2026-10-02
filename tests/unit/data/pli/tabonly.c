/* PLI 1.0 function with no veriusertfs: described only by hello.tab. */
#include "veriuser.h"
#include "acc_user.h"

int hello_tab_call(int data, int reason) {
    io_printf("TAB: hello from $hello_tab\n");
    return 0;
}
