/* Minimal VPI module: prints from its startup routine. */
#include <stdio.h>
#include "vpi_user.h"

static void xzm_vpi_register(void) {
    vpi_printf("xzm_vpi: startup routine ran\n");
}

void (*vlog_startup_routines[])(void) = {
    xzm_vpi_register,
    0
};
