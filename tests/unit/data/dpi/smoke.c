
#include <stdio.h>

#ifdef __cplusplus
extern "C" {
#endif


void dpi_func() {
    fprintf(stdout, "RES: dpi_func\n");
    fflush(stdout);
}

#ifdef __cplusplus
}
#endif