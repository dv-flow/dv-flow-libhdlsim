
#include <stdio.h>
#include "dpi_cfg.h"

/* Both must come from the cSource FileSet's defines */
#ifndef DPI_C_DEFINE
#error "DPI_C_DEFINE not passed to the C compile"
#endif
#if DPI_C_VALUE != 42
#error "DPI_C_VALUE not passed to the C compile"
#endif

#ifdef __cplusplus
extern "C" {
#endif

void dpi_func() {
    fprintf(stdout, "%s\n", DPI_CFG_MSG);
    fprintf(stdout, "RES: dpi_func\n");
    fflush(stdout);
}

#ifdef __cplusplus
}
#endif
