"""Local trusted-coordinator maintenance protocol; no HTTP or secret bootstrap.

The caller must obtain explicit user confirmation before destructive transitions
and observe authenticated trial health/child exit before finalize. A local pipe
is transport, not proof of user approval. Existing profile locks/journals apply.
"""
import json
from pathlib import Path
import sys
from uuid import UUID

from server.activation_trial_entry import MAX_REQUEST, read_pipe_line


def decode_request(data: bytes) -> dict:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("activation_control_request_invalid")
            value[key] = item
        return value

    if len(data) > MAX_REQUEST:
        raise ValueError("activation_control_request_invalid")
    value = json.loads(data, object_pairs_hook=unique)
    if not isinstance(value, dict) or not isinstance(value.get("action"), str):
        raise ValueError("activation_control_request_invalid")
    fields = {"backup": {"action", "name"}, "prepare": {"action", "archive", "candidate"},
              "rewrap": {"action", "candidate", "source_secret", "target_secret"},
              "switch": {"action", "candidate", "secret"}, "rollback": {"action"}, "inspect": {"action"},
              "finalize": {"action", "operation_id", "secret"}}
    if value["action"] == "rollback" and "operation_id" in value:
        fields["rollback"] = {"action", "operation_id"}
    if value["action"] not in fields or set(value) != fields[value["action"]]:
        raise ValueError("activation_control_request_invalid")
    if value["action"] == "backup":
        import re
        if not isinstance(value["name"], str) or not re.fullmatch(r"manual-[a-f0-9]{64}\.zip", value["name"]):
            raise ValueError("activation_control_request_invalid")
    for field in ("secret", "source_secret", "target_secret"):
        if field in value and (not isinstance(value[field], str) or not value[field].strip()
                               or "\0" in value[field] or len(value[field].encode()) > 8192):
            raise ValueError("activation_control_request_invalid")
    if "candidate" in value:
        name = value["candidate"]
        if (not isinstance(name, str) or not name or name in {".", ".."}
                or any(char in name for char in "/\\\0") or len(name.encode()) > 255
                or Path(name).name != name):
            raise ValueError("activation_control_request_invalid")
    if "archive" in value:
        archive = value["archive"]
        if (not isinstance(archive, str) or "\0" in archive or len(archive.encode()) > 4096
                or not Path(archive).is_absolute() or ".." in Path(archive).parts):
            raise ValueError("activation_control_request_invalid")
    if "operation_id" in value:
        identity = value["operation_id"]
        if not isinstance(identity, str) or str(UUID(identity)) != identity:
            raise ValueError("activation_control_request_invalid")
    return value


def run(sanitize_env) -> int:
    try:
        if "server.config" in sys.modules:
            raise ValueError("activation_control_runtime_already_loaded")
        request = decode_request(read_pipe_line(sys.stdin.fileno()))
        sanitize_env()
        from server.profile_paths import resolve_data_dir
        from server.services import profile_activation

        active = resolve_data_dir()
        if request["action"] == "backup":
            from server.services import backup
            from server.services.data_profile_lock import hold
            from server.services.upgrade_backup import check_space
            with hold(active / "arslan.db"):
                directory = active / "backups"
                if directory.is_symlink():
                    raise ValueError("unsafe_backup_directory")
                check_space(active / "arslan.db")
                directory.mkdir(mode=0o700, exist_ok=True)
                result = backup.create(active, directory / request["name"])
        elif request["action"] == "prepare":
            result = profile_activation.prepare_from_archive(active, Path(request["archive"]),
                                                             active.parent / request["candidate"])
        elif request["action"] == "rewrap":
            from server.services.recovery_rewrap import rewrap_candidate
            result = rewrap_candidate(active, active.parent / request["candidate"],
                                      request["source_secret"], request["target_secret"])
            result["candidate"] = request["candidate"]
        elif request["action"] == "switch":
            result = profile_activation.switch_for_trial(active, active.parent / request["candidate"], request["secret"])
        elif request["action"] == "rollback":
            result = profile_activation.rollback(active, request.get("operation_id"))
        elif request["action"] == "inspect":
            result = profile_activation.pending_operation(active)
        else:
            result = profile_activation.finalize(active, request["operation_id"], request["secret"])
        del request
    except Exception:  # noqa: BLE001 — no user data, paths or secrets in process errors
        print(json.dumps({"ok": False, "code": "activation_control_refused"}), flush=True)
        return 1
    print(json.dumps({"ok": True, "result": result}), flush=True)
    return 0
