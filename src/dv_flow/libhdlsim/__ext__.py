import os

def dvfm_packages():
    hdlsim_dir = os.path.dirname(os.path.abspath(__file__))

    return {
        'hdlsim': os.path.join(hdlsim_dir, "flow.dv"),
        'hdlsim.ivl': os.path.join(hdlsim_dir, "ivl_flow.dv"),
        'hdlsim.mti': os.path.join(hdlsim_dir, "mti_flow.dv"),
        'hdlsim.vcs': os.path.join(hdlsim_dir, "vcs_flow.dv"),
        'hdlsim.vlt': os.path.join(hdlsim_dir, "vlt_flow.dv"),
        'hdlsim.xsm': os.path.join(hdlsim_dir, "xsm_flow.dv"),
    }
