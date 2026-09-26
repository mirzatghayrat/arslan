//! Read an explicitly selected existing key; never bootstrap or repair it.
//! The native coordinator owns selection/approval and must trust parent folders.
//! Final-component no-follow is not protection from hostile ancestor replacement.
use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::Path;

// A typed proof of an existing external file, not approval to use/rewrite it.
// Parent folders must be trusted. Future external configuration changes are not
// preventable by this snapshot; the coordinator rechecks before every phase.
pub(crate) struct DurableSecret {
    secret: ExistingSecret,
    path: std::path::PathBuf,
    default_path: std::path::PathBuf,
    canonical: std::path::PathBuf,
    identity: (u64, u64, i64, i64, i64, i64),
}

fn identity(path: &Path) -> Result<(u64, u64, i64, i64, i64, i64), SecretError> {
    let m = std::fs::symlink_metadata(path).map_err(|_| SecretError::Unavailable)?;
    Ok((
        m.dev(),
        m.ino(),
        m.mtime(),
        m.mtime_nsec(),
        m.ctime(),
        m.ctime_nsec(),
    ))
}

impl DurableSecret {
    /// Mirrors supported normal bootstrap sources without any repair/generation.
    /// Recovery currently proves the default durable file only. Overrides must
    /// resolve to that same file: an environment-only custom location does not
    /// establish what a later independent Finder launch will read. Normal boot
    /// and its custom-location support remain unchanged.
    pub(crate) fn load(
        home: &Path,
        profile: &Path,
        environment: &str,
        explicit: Option<&str>,
        file_override: Option<&str>,
    ) -> Result<Self, SecretError> {
        if environment != "dev" || !home.is_absolute() || !profile.is_absolute() {
            return Err(SecretError::Unsafe);
        }
        let path = match file_override {
            None => home.join(".arslan/secret_key"),
            Some(raw) if raw.trim().is_empty() => return Err(SecretError::Unavailable),
            Some(raw) if raw.starts_with("~/") => home.join(&raw[2..]),
            Some(raw) => std::path::PathBuf::from(raw),
        };
        if !path.is_absolute()
            || path
                .components()
                .any(|p| p == std::path::Component::ParentDir)
            || path.to_string_lossy().contains(['$', '\0'])
        {
            return Err(SecretError::Unsafe);
        }
        let canonical = path.canonicalize().map_err(|_| SecretError::Unavailable)?;
        let default_path = home.join(".arslan/secret_key");
        let default = default_path
            .canonicalize()
            .map_err(|_| SecretError::Unavailable)?;
        if canonical != default {
            return Err(SecretError::Unsafe);
        }
        let profile = profile
            .canonicalize()
            .map_err(|_| SecretError::Unavailable)?;
        if canonical.starts_with(profile) {
            return Err(SecretError::Unsafe);
        }
        let before = identity(&path)?;
        let secret = read_existing(&path)?;
        if read_existing(&default_path)?.expose() != secret.expose()
            || identity(&default_path)? != before
        {
            return Err(SecretError::Changed);
        }
        if identity(&path)? != before {
            return Err(SecretError::Changed);
        }
        if let Some(value) = explicit.filter(|value| !value.trim().is_empty()) {
            let supplied = validate(value.to_owned())?;
            if supplied.expose().trim() != secret.expose().trim() {
                return Err(SecretError::Changed);
            }
        }
        Ok(Self {
            secret,
            path,
            default_path,
            canonical,
            identity: before,
        })
    }

    pub(crate) fn secret(&self) -> &ExistingSecret {
        &self.secret
    }

    pub(crate) fn recheck(&self) -> Result<(), SecretError> {
        if self
            .path
            .canonicalize()
            .map_err(|_| SecretError::Unavailable)?
            != self.canonical
            || self
                .default_path
                .canonicalize()
                .map_err(|_| SecretError::Unavailable)?
                != self.canonical
            || identity(&self.default_path)? != self.identity
            || read_existing(&self.default_path)?.expose() != self.secret.expose()
            || identity(&self.path)? != self.identity
            || read_existing(&self.path)?.expose() != self.secret.expose()
            || identity(&self.path)? != self.identity
            || identity(&self.default_path)? != self.identity
        {
            return Err(SecretError::Changed);
        }
        Ok(())
    }
}

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
    fn durable_default_survives_readonly_checks_and_matching_explicit_key() {
        let fixture = Fixture::new();
        let profile = fixture.0.join("profile");
        std::fs::create_dir(&profile).unwrap();
        std::fs::create_dir(fixture.0.join(".arslan")).unwrap();
        let file = fixture.0.join(".arslan/secret_key");
        std::fs::write(&file, b"  synthetic-durable\n").unwrap();
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o400)).unwrap();
        for override_path in [None, Some("~/.arslan/secret_key"), file.to_str()] {
            let proof = DurableSecret::load(
                &fixture.0,
                &profile,
                "dev",
                Some("synthetic-durable"),
                override_path,
            )
            .unwrap_or_else(|_| panic!("refused durable fixture"));
            assert_eq!(proof.secret().expose(), "  synthetic-durable\n");
            assert_eq!(proof.recheck(), Ok(()));
        }
        assert_eq!(std::fs::metadata(&file).unwrap().mode() & 0o777, 0o400);
        for (mode, explicit, override_path) in [
            ("prod", None, None),
            ("dev", Some("different"), None),
            ("dev", None, Some("")),
            ("dev", None, Some("relative")),
            ("dev", None, Some("$HOME/.arslan/secret_key")),
        ] {
            assert!(
                DurableSecret::load(&fixture.0, &profile, mode, explicit, override_path).is_err()
            );
        }
        let alternate = fixture.key(b"synthetic-durable");
        assert!(
            DurableSecret::load(&fixture.0, &profile, "dev", None, alternate.to_str()).is_err()
        );
        let proof = DurableSecret::load(&fixture.0, &profile, "dev", None, None)
            .unwrap_or_else(|_| panic!());
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600)).unwrap();
        assert!(proof.recheck().is_err());
    }

    #[test]
    fn durable_file_replacement_and_inside_profile_are_refused() {
        let fixture = Fixture::new();
        let folder = fixture.0.join(".arslan");
        std::fs::create_dir(&folder).unwrap();
        let file = folder.join("secret_key");
        std::fs::write(&file, b"synthetic-durable").unwrap();
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600)).unwrap();
        assert!(DurableSecret::load(&fixture.0, &folder, "dev", None, None).is_err());
        let profile = fixture.0.join("profile");
        std::fs::create_dir(&profile).unwrap();
        let proof = DurableSecret::load(&fixture.0, &profile, "dev", None, None)
            .unwrap_or_else(|_| panic!());
        let replacement = fixture.key(b"synthetic-durable");
        std::fs::rename(replacement, &file).unwrap();
        assert!(proof.recheck().is_err());
        std::fs::remove_file(&file).unwrap();
        assert!(
            DurableSecret::load(&fixture.0, &profile, "dev", Some("synthetic-durable"), None)
                .is_err()
        );
        assert!(!file.exists());
        let alternate = fixture.key(b"synthetic-durable");
        symlink(&alternate, &file).unwrap();
        assert!(
            DurableSecret::load(&fixture.0, &profile, "dev", None, alternate.to_str()).is_err()
        );
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
