"""Looking at the user's own local network, and reaching machines on it."""
from server.registry.tool import Tool

NETWORK = (
    # LAN discovery (P3a): offered only when the user turned it on. Read-only —
    # it looks at the network, it does not reach anything on it.
    Tool("scan_local_network",
         "See which machines are on the user's own local network "
         "(IP, open ports, hardware vendor). READ-ONLY: it does "
         "not connect to, log into, or run anything on them. "
         "args: {} — the network is derived from this machine.",
         {"type": "object", "properties": {}, "additionalProperties": False},
         offered=lambda offer: offer.lan),
    # SSH reach (P3b): offered only when the user turned it on. ssh_probe looks;
    # ssh_run asks every time — the description says so, because a model that
    # believes a tool is silent will plan around a dialog that is going to appear.
    Tool("ssh_probe",
         "Check whether a machine on the local network accepts SSH "
         "and report its host key fingerprint. READ-ONLY: it logs "
         "into nothing and runs nothing. args: {host} — an IPv4 "
         "address, e.g. 192.168.1.8 (names cannot be resolved).",
         {
             "type": "object",
             "properties": {"host": {"type": "string", "minLength": 1,
                                     "description": "An IPv4 address on the local network, e.g. 192.168.1.8."}},
             "required": ["host"],
             "additionalProperties": False,
         },
         offered=lambda offer: offer.ssh),
    Tool("enroll_node",
         "ASK the user to enrol a machine so its host key is "
         "remembered. args: {host, user, name}. This enrols "
         "NOTHING by itself: it shows the user a card with the "
         "machine's fingerprint, which they confirm. Enrolling "
         "only saves re-checking the fingerprint — commands on an "
         "enrolled machine still need approval every time. Enrol a "
         "machine before running commands on it: running is offered "
         "once one is enrolled.",
         {
             "type": "object",
             "properties": {
                 "host": {"type": "string", "minLength": 1, "description": "The machine's IPv4 address."},
                 "user": {"type": "string", "minLength": 1, "description": "The username to log in as."},
                 "name": {"type": "string", "minLength": 1, "maxLength": 60, "description": "A name for the machine."},
             },
             "required": ["host", "user", "name"],
             "additionalProperties": False,
         },
         offered=lambda offer: offer.ssh),
    # C3b (⓪Plan's call A on the user's card U3): running needs an enrolled machine, so a first
    # command goes probe → enrol (its host key pinned) → run. With one enrolled, ssh_run still
    # reaches an unenrolled host through its fingerprint card; C3b does not change that.
    Tool("ssh_run",
         "Run ONE whitelisted command on another machine over SSH. "
         "args: {host, user, command, argv}. The user is asked to "
         "approve EVERY call, including read-only ones — enrolling "
         "a machine does NOT change that — and the card shows the "
         "host key fingerprint. Scheduled runs cannot use this.",
         {
             "type": "object",
             "properties": {
                 "host": {"type": "string", "minLength": 1, "description": "The machine's IPv4 address."},
                 "user": {"type": "string", "minLength": 1, "description": "The username to log in as."},
                 "command": {"type": "string", "minLength": 1, "description": "One whitelisted program name, e.g. 'uptime'."},
                 "argv": {"type": "array", "items": {"type": "string"}, "description": "Its arguments, one per item."},
             },
             "required": ["host", "user", "command"],
             "additionalProperties": False,
         },
         offered=lambda offer: offer.enrolled),
    Tool("list_nodes",
         "List the machines the user has enrolled (name, address, "
         "username). READ-ONLY. args: {}.",
         {"type": "object", "properties": {}, "additionalProperties": False},
         offered=lambda offer: offer.enrolled),
)
