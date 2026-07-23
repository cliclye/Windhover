use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::Manager;
use url::Url;

struct Backend(Mutex<Option<Child>>);

fn repo_root() -> PathBuf {
    // desktop/src-tauri → desktop → repo root (dev builds)
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."))
}

fn health_ok() -> bool {
    let mut stream = match TcpStream::connect_timeout(
        &"127.0.0.1:8000".parse().unwrap(),
        Duration::from_millis(200),
    ) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(400)));
    let _ = stream.write_all(
        b"GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n",
    );
    let mut buf = [0u8; 256];
    let n = stream.read(&mut buf).unwrap_or(0);
    let body = String::from_utf8_lossy(&buf[..n]);
    body.contains("200") && body.contains("\"ok\"")
}

/// Candidate dirs for packaged sidecars (Tauri externalBin lives next to the exe).
fn sidecar_dirs(app: Option<&tauri::AppHandle>) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            dirs.push(parent.to_path_buf());
            // Some installers nest under a resources/ or binaries/ folder.
            dirs.push(parent.join("binaries"));
            dirs.push(parent.join("resources"));
        }
    }
    if let Some(app) = app {
        if let Ok(p) = app.path().resource_dir() {
            dirs.push(p.clone());
            dirs.push(p.join("binaries"));
        }
    }
    dirs
}

fn find_sidecar(dirs: &[PathBuf], names: &[&str]) -> Option<PathBuf> {
    for dir in dirs {
        for name in names {
            let p = dir.join(name);
            if p.is_file() {
                return Some(p);
            }
        }
    }
    None
}

fn sidecar_server(dirs: &[PathBuf]) -> Option<PathBuf> {
    #[cfg(windows)]
    let names = ["windhover-server.exe", "windhover-server"];
    #[cfg(not(windows))]
    let names = ["windhover-server", "windhover-server.exe"];
    find_sidecar(dirs, &names)
}

fn sidecar_engine(dirs: &[PathBuf]) -> Option<PathBuf> {
    #[cfg(windows)]
    let names = ["windhover-engine.exe", "windhover-engine"];
    #[cfg(not(windows))]
    let names = ["windhover-engine", "windhover-engine.exe"];
    find_sidecar(dirs, &names)
}

fn spawn_command(mut cmd: Command) -> Option<Child> {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd.stdout(Stdio::null()).stderr(Stdio::null()).spawn().ok()
}

fn start_backend(app: Option<&tauri::AppHandle>) -> Option<Child> {
    // If something healthy is already on :8000 (e.g. `./windhover app`), reuse it.
    if health_ok() {
        eprintln!("[windhover-desktop] reusing existing server on :8000");
        return None;
    }

    // 1) Packaged sidecar (Windows NSIS / Mac .app with externalBin)
    let dirs = sidecar_dirs(app);
    if let Some(server) = sidecar_server(&dirs) {
        let mut cmd = Command::new(&server);
        cmd.env("WINDHOVER_HOST", "127.0.0.1")
            .env("WINDHOVER_PORT", "8000")
            .env("WINDHOVER_APP_NO_AUTOPULL", "1")
            // Avoid Windows cp1252 UnicodeEncodeError on download progress (U+2192).
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env("HF_HUB_DISABLE_PROGRESS_BARS", "1");
        if let Some(eng) = sidecar_engine(&dirs) {
            cmd.env("WINDHOVER_ENGINE", &eng);
        }
        // Prefer the sidecar's directory as cwd (MEIPASS is still used by PyInstaller).
        if let Some(parent) = server.parent() {
            cmd.current_dir(parent);
        }
        eprintln!(
            "[windhover-desktop] starting sidecar {}",
            server.display()
        );
        if let Some(mut child) = spawn_command(cmd) {
            for _ in 0..80 {
                if health_ok() {
                    return Some(child);
                }
                if let Ok(Some(status)) = child.try_wait() {
                    eprintln!("[windhover-desktop] sidecar exited early: {status}");
                    break;
                }
                thread::sleep(Duration::from_millis(100));
            }
        }
    }

    // 2) Dev fallback: repo-root `python windhover app`
    let root = repo_root();
    let cli = root.join("windhover");
    let cli = if cli.is_file() {
        cli
    } else {
        root.join("kestrel")
    };
    if !cli.is_file() {
        eprintln!(
            "[windhover-desktop] missing CLI at {} and no packaged sidecar",
            cli.display()
        );
        return None;
    }

    #[cfg(windows)]
    let venv_candidates = [
        root.join("c/.venv/Scripts/python.exe"),
        root.join("c/.venv/Scripts/python"),
    ];
    #[cfg(not(windows))]
    let venv_candidates = [root.join("c/.venv/bin/python3"), root.join("c/.venv/bin/python")];

    let mut python = PathBuf::from(if cfg!(windows) { "python" } else { "python3" });
    for c in &venv_candidates {
        if c.is_file() {
            python = c.clone();
            break;
        }
    }

    let mut cmd = Command::new(&python);
    cmd.arg(&cli)
        .arg("app")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg("8000")
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .env("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        .current_dir(&root);

    let mut child = spawn_command(cmd)?;

    for _ in 0..50 {
        if health_ok() {
            return Some(child);
        }
        if let Ok(Some(status)) = child.try_wait() {
            eprintln!("[windhover-desktop] backend exited early: {status}");
            return None;
        }
        thread::sleep(Duration::from_millis(100));
    }
    eprintln!("[windhover-desktop] backend started (health still warming up)");
    Some(child)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();
            let child = start_backend(Some(&handle));
            app.manage(Backend(Mutex::new(child)));

            if let Some(win) = app.get_webview_window("main") {
                let _ = win.set_title("Windhover");
                // Prefer the live Windhover server (UI + API same-origin).
                let win2 = win.clone();
                thread::spawn(move || {
                    for _ in 0..90 {
                        if health_ok() {
                            let url = Url::parse("http://127.0.0.1:8000/").expect("static url");
                            if let Err(e) = win2.navigate(url) {
                                eprintln!("[windhover-desktop] navigate failed: {e}");
                                let _ = win2.eval(
                                    "window.location.replace('http://127.0.0.1:8000/')",
                                );
                            }
                            break;
                        }
                        thread::sleep(Duration::from_millis(100));
                    }
                });
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.try_state::<Backend>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to run the Windhover application");
}
