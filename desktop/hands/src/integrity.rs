//! agent-desktop is checked against the sha256 recorded inside Hands' own
//! signed bundle before every run.
//!
//! Why it lives OUTSIDE the bundle (measured 2026-10-03 on the user's Mac): with
//! agent-desktop inside `Arslan Hands.app/Contents/MacOS`, running it on its own
//! (responsibility disclaimed) reported Accessibility *granted* — macOS lent it
//! the bundle's grant, so any process could have driven apps with it, past the
//! token, the peer check and every card. Next to the bundle it is just a file;
//! run by Hands it inherits Hands' grant as its child, run by anything else it
//! has none. Being a plain file it could be swapped, and a swapped binary run by
//! Hands would inherit the grant — hence this check.

use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

/// (dev, inode, size, ctime, ctime ns) of a file.
type Stamp = (u64, u64, u64, i64, i64);

/// The binary Hands may run, and the hash it must have.
#[derive(Debug)]
pub struct Pinned {
    pub path: PathBuf,
    pub sha256: String,
    /// The last file that matched. ctime, not mtime: a user process can set
    /// mtime back, never ctime.
    verified: Mutex<Option<Stamp>>,
}

impl Pinned {
    pub fn new(path: PathBuf, sha256: &str) -> Pinned {
        Pinned {
            path,
            sha256: sha256.trim().to_ascii_lowercase(),
            verified: Mutex::new(None),
        }
    }

    /// Ok if the file on disk is the recorded build. Rehashes only when the file
    /// changed since the last match.
    pub fn check(&self) -> Result<(), String> {
        let meta =
            std::fs::metadata(&self.path).map_err(|e| format!("agent-desktop is missing ({e})"))?;
        let stamp = (
            meta.dev(),
            meta.ino(),
            meta.size(),
            meta.ctime(),
            meta.ctime_nsec(),
        );
        let mut verified = self.verified.lock().unwrap_or_else(|p| p.into_inner());
        if *verified == Some(stamp) {
            return Ok(());
        }
        let actual =
            sha256_file(&self.path).map_err(|e| format!("cannot read agent-desktop ({e})"))?;
        if actual != self.sha256 {
            *verified = None;
            return Err("agent-desktop is not the build Arslan Hands was signed with".into());
        }
        *verified = Some(stamp);
        Ok(())
    }
}

/// The first word of `Resources/agent-desktop.sha256`, if it is a sha256.
pub fn recorded(record: &Path) -> Option<String> {
    let text = std::fs::read_to_string(record).ok()?;
    let word = text.split_whitespace().next()?.to_ascii_lowercase();
    (word.len() == 64 && word.bytes().all(|b| b.is_ascii_hexdigit())).then_some(word)
}

pub fn sha256_file(path: &Path) -> std::io::Result<String> {
    let mut file = std::fs::File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buf = vec![0u8; 64 * 1024];
    loop {
        let n = file.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(hasher.hex())
}

/// SHA-256 (FIPS 180-4). Small and dependency-free on purpose: this process
/// holds Accessibility, and every crate it links runs with it.
pub struct Sha256 {
    state: [u32; 8],
    block: [u8; 64],
    filled: usize,
    length: u64,
}

const K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

impl Default for Sha256 {
    fn default() -> Self {
        Self::new()
    }
}

impl Sha256 {
    pub fn new() -> Sha256 {
        Sha256 {
            state: [
                0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
                0x5be0cd19,
            ],
            block: [0; 64],
            filled: 0,
            length: 0,
        }
    }

    pub fn update(&mut self, mut data: &[u8]) {
        self.length = self.length.wrapping_add(data.len() as u64);
        while !data.is_empty() {
            let take = (64 - self.filled).min(data.len());
            self.block[self.filled..self.filled + take].copy_from_slice(&data[..take]);
            self.filled += take;
            data = &data[take..];
            if self.filled == 64 {
                let block = self.block;
                self.compress(&block);
                self.filled = 0;
            }
        }
    }

    pub fn hex(mut self) -> String {
        let bits = self.length.wrapping_mul(8);
        self.update(&[0x80]);
        while self.filled != 56 {
            self.update(&[0]);
        }
        let block = {
            let mut b = self.block;
            b[56..].copy_from_slice(&bits.to_be_bytes());
            b
        };
        self.compress(&block);
        self.state.iter().map(|w| format!("{w:08x}")).collect()
    }

    fn compress(&mut self, block: &[u8; 64]) {
        let mut w = [0u32; 64];
        for (i, chunk) in block.chunks(4).enumerate() {
            w[i] = u32::from_be_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = self.state;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ (!e & g);
            let t1 = h
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        for (s, v) in self.state.iter_mut().zip([a, b, c, d, e, f, g, h]) {
            *s = s.wrapping_add(v);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hash(data: &[u8]) -> String {
        let mut h = Sha256::new();
        h.update(data);
        h.hex()
    }

    #[test]
    fn known_vectors() {
        assert_eq!(
            hash(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            hash(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(
            hash(b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"),
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"
        );
        let million = vec![b'a'; 1_000_000];
        assert_eq!(
            hash(&million),
            "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"
        );
    }

    #[test]
    fn a_swapped_binary_is_refused_and_the_recorded_one_runs() {
        let dir = std::env::temp_dir().join(format!("hands-integrity-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let bin = dir.join("agent-desktop");
        std::fs::write(&bin, b"the real build").unwrap();
        let record = dir.join("agent-desktop.sha256");
        std::fs::write(
            &record,
            format!("{}  agent-desktop, signed\n", hash(b"the real build")),
        )
        .unwrap();
        let pinned = Pinned::new(bin.clone(), &recorded(&record).unwrap());
        assert!(pinned.check().is_ok());
        std::fs::write(&bin, b"something else that wants Accessibility").unwrap();
        assert!(pinned.check().unwrap_err().contains("not the build"));
        std::fs::remove_file(&bin).unwrap();
        assert!(pinned.check().unwrap_err().contains("missing"));
        assert_eq!(recorded(&dir.join("nope")), None);
        std::fs::write(&record, "not-a-hash").unwrap();
        assert_eq!(recorded(&record), None);
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
