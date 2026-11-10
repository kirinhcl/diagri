from growbridge.compute.backend import JobTemplate, ParamSpec

TEMPLATE = JobTemplate(
    id="segment",
    version=1,
    script="segment.sh",
    parameters={
        "batch_size": ParamSpec(kind="int", minimum=1, maximum=512, default=32),
        "model": ParamSpec(kind="str", choices=("small", "large"), default="small"),
        "threshold": ParamSpec(kind="float", minimum=0.0, maximum=1.0, default=0.5),
        "epochs": ParamSpec(kind="int", minimum=1, maximum=100),
        "verbose": ParamSpec(kind="bool", default=False),
    },
    max_cpu_hours=10.0,
    max_storage_gb=5.0,
    result_changing=("batch_size",),
)
GOOD_PARAMS = {"epochs": 3}
INPUTS = {"images": "snapshots/s1/images"}
MEMBERS = {"alice": "csc_alice", "bob": "csc_bob"}
