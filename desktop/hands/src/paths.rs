//! Where Hands keeps its socket, token and agent-desktop state.
//!
//! Fixed and derived here, from the account database — never from arguments or
//! the environment: `open --args` and `open --env` are available to any command,
//! and a folder a command chose would be a socket and token a command can read.

use std::ffi::CStr;
use std::fs;
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::{Path, PathBuf};

pub const FOLDER: &str = "Library/Application Support/Arslan Hands";
pub const SOCKET: &str = "s.sock";
pub const READY: &str = "ready.json";
pub const LOCK: &str = "lock";
pub const AGENT_DESKTOP_HOME: &str = "ad";
/// `sun_path` is 104 bytes on macOS, including the terminating NUL.
pub const MAX_SOCKET_PATH: usize = 103;

/// The account's home directory from getpwuid_r, ignoring $HOME.
pub fn account_home() -> Option<PathBuf> {
    let mut buf = vec![0u8; 4096];
    let mut pwd: libc::passwd = unsafe { std::mem::zeroed() };
    let mut result: *mut libc::passwd = std::ptr::null_mut();
    let rc = unsafe {
        libc::getpwuid_r(
            libc::getuid(),
            &mut pwd,
            buf.as_mut_ptr().cast(),
            buf.len(),
            &mut result,
        )
    };
    if rc != 0 || result.is_null() || pwd.pw_dir.is_null() {
        return None;
    }
    let dir = unsafe { CStr::from_ptr(pwd.pw_dir) }.to_str().ok()?;
    Some(PathBuf::from(dir))
}

pub fn folder(home: &Path) -> PathBuf {
    home.join(FOLDER)
}

/// Create (or tighten) a private folder: a real directory, not a symlink, owned
/// by this user, mode 0700. agent-desktop refuses a state root that others can
/// read, and so does Hands.
pub fn ensure_private_dir(dir: &Path) -> Result<(), String> {
    if !dir.exists() {
        fs::create_dir_all(dir).map_err(|e| format!("cannot create {}: {e}", dir.display()))?;
    }
    let meta =
        fs::symlink_metadata(dir).map_err(|e| format!("cannot stat {}: {e}", dir.display()))?;
    if !meta.file_type().is_dir() {
        return Err(format!("{} is not a directory", dir.display()));
    }
    if meta.uid() != unsafe { libc::getuid() } {
        return Err(format!("{} belongs to another user", dir.display()));
    }
    if meta.permissions().mode() & 0o777 != 0o700 {
        fs::set_permissions(dir, fs::Permissions::from_mode(0o700))
            .map_err(|e| format!("cannot chmod {}: {e}", dir.display()))?;
    }
    Ok(())
}

pub fn socket_path_fits(path: &Path) -> bool {
    path.as_os_str().len() <= MAX_SOCKET_PATH
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_folder_comes_from_the_account_not_home() {
        let before = account_home().expect("a home directory");
        std::env::set_var("HOME", "/tmp/elsewhere");
        assert_eq!(account_home().unwrap(), before);
        assert!(folder(&before).ends_with("Library/Application Support/Arslan Hands"));
    }

    #[test]
    fn private_dirs_are_tightened_and_symlinks_refused() {
        let base = std::env::temp_dir().join(format!("hands-paths-{}", std::process::id()));
        let _ = fs::remove_dir_all(&base);
        let dir = base.join("f");
        fs::create_dir_all(&dir).unwrap();
        fs::set_permissions(&dir, fs::Permissions::from_mode(0o755)).unwrap();
        ensure_private_dir(&dir).unwrap();
        assert_eq!(
            fs::metadata(&dir).unwrap().permissions().mode() & 0o777,
            0o700
        );
        let link = base.join("l");
        std::os::unix::fs::symlink(&dir, &link).unwrap();
        assert!(ensure_private_dir(&link).is_err());
        fs::remove_dir_all(&base).unwrap();
    }

    #[test]
    fn long_socket_paths_are_refused() {
        assert!(socket_path_fits(Path::new(
            "/Users/a/Library/Application Support/Arslan Hands/s.sock"
        )));
        assert!(!socket_path_fits(&PathBuf::from(format!(
            "/{}/s.sock",
            "x".repeat(100)
        ))));
    }
}
