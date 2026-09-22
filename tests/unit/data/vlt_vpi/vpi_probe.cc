// Exercises the same pattern the UVM DPI layer uses: a DPI-C function whose
// implementation calls into VPI. Requires --vpi, but no custom C++ main.
#include <cstddef>

#include "svdpi.h"
#include "vpi_user.h"

extern "C" int probe_sig(const char* path) {
    vpiHandle h = vpi_handle_by_name((PLI_BYTE8*)path, NULL);
    if (!h) return 0;
    s_vpi_value val;
    val.format = vpiIntVal;
    vpi_get_value(h, &val);
    return (val.value.integer == (PLI_INT32)0xdeadbeef) ? 1 : 0;
}
