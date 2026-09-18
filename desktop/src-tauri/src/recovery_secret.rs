//! Read an explicitly selected existing key; never bootstrap or repair it.
//! The native coordinator owns selection/approval and must trust parent folders.
//! Final-component no-follow is not protection from hostile ancestor replacement.
use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::Path;

const MAX_BYTES: u64 = 8192;

// Deliberately no Debug/Display/Serialize: never include a key in diagnostics.
pub(crate) struct ExistingSecret(String);

#[derive(Debug, PartialEq)]
pub(crate) enum SecretError {
    Unavailable,
    Unsafe,
    Invalid,
    Changed,
}

impl ExistingSecret {
    pub(crate) fn expose(&self) -> &str {
        &self.0
    }
}

fn validate(value: String) -> Result<ExistingSecret, SecretError> {
    if value.len() > MAX_BYTES as usize || value.trim().is_empty() || value.contains('\0') {
        return Err(SecretError::Invalid);
    }
    // Preserve bytes; the existing Python crypto implementation owns trimming.
    Ok(ExistingSecret(value))
}

pub(crate) fn read_existing(path: &Path) -> Result<ExistingSecret, SecretError> {
    if !path.is_absolute() {
        return Err(SecretError::Unsafe);
    }
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
        .open(path)
        .map_err(|_| SecretError::Unavailable)?;
    let before = file.metadata().map_err(|_| SecretError::Unavailable)?;
    // SAFETY: geteuid has no arguments or memory preconditions.
    let owner = unsafe { libc::geteuid() };
    if !before.is_file()
        || before.uid() != owner
        || before.nlink() != 1
        || before.mode() & 0o077 != 0
    {
        return Err(SecretError::Unsafe);
    }
    if before.len() > MAX_BYTES {
        return Err(SecretError::Invalid);
    }
    let mut value = String::new();
    (&file)
        .take(MAX_BYTES + 1)
        .read_to_string(&mut value)
        .map_err(|_| SecretError::Invalid)?;
    let after = file.metadata().map_err(|_| SecretError::Unavailable)?;
    if before.len() != after.len()
        || before.mtime() != after.mtime()
        || before.mtime_nsec() != after.mtime_nsec()
        || before.ctime() != after.ctime()
        || before.ctime_nsec() != after.ctime_nsec()
        || before.mode() != after.mode()
        || before.nlink() != after.nlink()
        || before.uid() != after.uid()
    {
        return Err(SecretError::Changed);
    }
    validate(value)
}

/// Explicit nonblank secret takes precedence; no environment/path discovery here.
pub(crate) fn prepare(
    explicit: Option<&str>,
    selected_file: &Path,
) -> Result<ExistingSecret, SecretError> {
    match explicit.filter(|value| !value.trim().is_empty()) {
        Some(value) => validate(value.to_owned()),
        None => read_existing(selected_file),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::{symlink, PermissionsExt};

    struct Fixture(std::path::PathBuf);
    impl Fixture {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "arslan-secret-fixture-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
            std::fs::create_dir(&path).unwrap();
            Self(path)
        }
        fn key(&self, bytes: &[u8]) -> std::path::PathBuf {
            let path = self.0.join("key");
            std::fs::write(&path, bytes).unwrap();
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
            path
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).unwrap();
        }
    }

    #[test]
    fn existing_key_is_preserved_without_repair() {
        let fixture = Fixture::new();
        let path = fixture.key(b"  synthetic-secret\n");
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o400)).unwrap();
        assert_eq!(
            read_existing(&path)
                .unwrap_or_else(|_| panic!("refused fixture"))
                .expose(),
            "  synthetic-secret\n"
        );
        assert_eq!(std::fs::read(&path).unwrap(), b"  synthetic-secret\n");
        assert_eq!(std::fs::metadata(&path).unwrap().mode() & 0o777, 0o400);
    }

    #[test]
    fn absent_key_never_creates_parents_or_files() {
        let fixture = Fixture::new();
        assert!(matches!(
            read_existing(&fixture.0.join("missing/key")),
            Err(SecretError::Unavailable)
        ));
        assert_eq!(std::fs::read_dir(&fixture.0).unwrap().count(), 0);
    }

    #[test]
    fn explicit_key_does_not_touch_selected_path() {
        assert_eq!(
            prepare(
                Some("synthetic-explicit"),
                Path::new("not-an-absolute-path")
            )
            .unwrap_or_else(|_| panic!("refused fixture"))
            .expose(),
            "synthetic-explicit"
        );
        assert!(matches!(
            prepare(Some("\0"), Path::new("unused")),
            Err(SecretError::Invalid)
        ));
    }

    #[test]
    fn rejects_invalid_content_without_rewriting() {
        let fixture = Fixture::new();
        for bytes in [
            vec![],
            b" \n\t".to_vec(),
            vec![0xff],
            vec![b'a'; 8193],
            b"a\0b".to_vec(),
        ] {
            let path = fixture.key(&bytes);
            assert!(matches!(read_existing(&path), Err(SecretError::Invalid)));
            assert_eq!(std::fs::read(path).unwrap(), bytes);
        }
    }

    #[test]
    fn accepts_bounded_key_and_blank_explicit_uses_selected_file() {
        let fixture = Fixture::new();
        let bytes = vec![b'a'; MAX_BYTES as usize];
        let path = fixture.key(&bytes);
        let secret = prepare(Some(" \n"), &path).unwrap_or_else(|_| panic!("refused fixture"));
        assert_eq!(secret.expose().as_bytes(), bytes);
        assert!(matches!(
            read_existing(Path::new("relative/key")),
            Err(SecretError::Unsafe)
        ));
        let oversized = "a".repeat(MAX_BYTES as usize + 1);
        assert!(matches!(
            prepare(Some(&oversized), &path),
            Err(SecretError::Invalid)
        ));
    }

    #[test]
    fn rejects_links_shared_permissions_and_directories() {
        let fixture = Fixture::new();
        let path = fixture.key(b"synthetic-only");
        let link = fixture.0.join("link");
        symlink(&path, &link).unwrap();
        assert!(read_existing(&link).is_err());
        std::fs::remove_file(&link).unwrap();
        std::fs::hard_link(&path, &link).unwrap();
        assert!(matches!(read_existing(&path), Err(SecretError::Unsafe)));
        std::fs::remove_file(&link).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        assert!(matches!(read_existing(&path), Err(SecretError::Unsafe)));
        assert_eq!(std::fs::metadata(&path).unwrap().mode() & 0o777, 0o644);
        assert!(matches!(
            read_existing(&fixture.0),
            Err(SecretError::Unsafe)
        ));
    }

    #[test]
    fn fifo_is_refused_without_waiting_for_a_writer() {
        use std::os::unix::ffi::OsStrExt;
        let fixture = Fixture::new();
        let path = fixture.0.join("fifo");
        let name = std::ffi::CString::new(path.as_os_str().as_bytes()).unwrap();
        // SAFETY: name is a live NUL-terminated path in our disposable directory.
        assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
        assert!(matches!(read_existing(&path), Err(SecretError::Unsafe)));
    }
}
