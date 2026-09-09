use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::Serialize;
use tauri::State;

/// The user-chosen library root. All FS commands are scoped to it at runtime,
/// so the webview can never read or write outside the opened folder.
#[derive(Default)]
struct AppState {
    root: Mutex<Option<PathBuf>>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct TreeNode {
    name: String,
    path: String,
    kind: String, // "dir" | "pdf" | "md" | "jsonl" | "other"
    has_md: bool, // PDFs: sibling <stem>.md exists?
    has_spans: bool,
    size: u64,
    children: Option<Vec<TreeNode>>,
}

fn classify(p: &Path) -> (&'static str, bool, bool, u64) {
    let name = p
        .file_name()
        .map(|s| s.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    let md = p.with_extension("md");
    let spans = p.with_extension(""); // <stem>.pdf -> <stem>
    let spans_jsonl = PathBuf::from(format!("{}.spans.jsonl", spans.display()));
    let has_md = md.is_file();
    let has_spans = spans_jsonl.is_file();
    let size = fs::metadata(p).map(|m| m.len()).unwrap_or(0);
    let kind = if name.ends_with(".pdf") {
        "pdf"
    } else if name.ends_with(".md") {
        "md"
    } else if name.ends_with(".spans.jsonl") || name.ends_with(".jsonl") {
        "jsonl"
    } else {
        "other"
    };
    (kind, has_md, has_spans, size)
}

fn build_node(p: &Path, depth: usize) -> Option<TreeNode> {
    let name = p.file_name()?.to_string_lossy().to_string();
    if name.starts_with('.') {
        return None; // skip dotfiles
    }
    if p.is_dir() {
        // Skip heavy/noisy dirs common in paper libraries.
        if matches!(
            name.as_str(),
            "node_modules" | ".git" | "__pycache__" | ".venv"
        ) {
            return None;
        }
        let children = (depth < 8)
            .then(|| {
                let mut kids: Vec<TreeNode> = fs::read_dir(p)
                    .ok()?
                    .filter_map(|e| build_node(&e.ok()?.path(), depth + 1))
                    .collect();
                kids.sort_by(|a, b| {
                    a.kind
                        .cmp(&b.kind)
                        .then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
                });
                Some(kids)
            })
            .flatten();
        Some(TreeNode {
            name,
            path: p.to_string_lossy().into_owned(),
            kind: "dir".into(),
            has_md: false,
            has_spans: false,
            size: 0,
            children,
        })
    } else {
        let (kind, has_md, has_spans, size) = classify(p);
        // Only surface files the UI can use; hide the rest to keep the tree clean.
        if kind == "other" {
            return None;
        }
        Some(TreeNode {
            name,
            path: p.to_string_lossy().into_owned(),
            kind: kind.into(),
            has_md,
            has_spans,
            size,
            children: None,
        })
    }
}

#[tauri::command]
fn set_root(app: tauri::AppHandle, state: State<AppState>, path: String) -> Result<(), String> {
    let p = PathBuf::from(&path);
    if !p.is_dir() {
        return Err(format!("not a directory: {}", path));
    }
    *state.root.lock().unwrap() = Some(p.clone());
    // Widen the scoped fs plugin so the webview can fetch PDF bytes anywhere
    // under the root (used by the preview pane via convertFileSrc + fetch).
    // Recursive: paper libraries keep PDFs in subfolders.
    use tauri_plugin_fs::FsExt;
    app.fs_scope()
        .allow_directory(&p, true)
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn get_root(state: State<AppState>) -> Option<String> {
    state
        .root
        .lock()
        .unwrap()
        .as_ref()
        .map(|p| p.to_string_lossy().into_owned())
}

#[tauri::command]
fn list_tree(state: State<AppState>) -> Result<Option<TreeNode>, String> {
    let root = state.root.lock().unwrap().clone();
    match root {
        Some(root) => build_node(&root, 0).map_or(Err("cannot read root".into()), |mut n| {
            // Root node itself is synthetic (no name filter applied).
            let mut kids: Vec<TreeNode> = fs::read_dir(&root)
                .map_err(|e| e.to_string())?
                .filter_map(|e| build_node(&e.ok()?.path(), 1))
                .collect();
            kids.sort_by(|a, b| {
                a.kind
                    .cmp(&b.kind)
                    .then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
            });
            n.children = Some(kids);
            Ok(Some(n))
        }),
        None => Ok(None),
    }
}

/// Read a UTF-8 text file, but only if it lives inside the library root.
#[tauri::command]
fn read_text_file(state: State<AppState>, path: String) -> Result<String, String> {
    let root = state.root.lock().unwrap().clone().ok_or("no root set")?;
    let p = PathBuf::from(&path);
    if !p.starts_with(&root) {
        return Err("path outside library root".into());
    }
    fs::read_to_string(&p).map_err(|e| e.to_string())
}

/// Write a UTF-8 text file inside the library root (creates the file; the
/// parent dir must already exist — the UI only writes next to opened PDFs).
#[tauri::command]
fn write_text_file(state: State<AppState>, path: String, contents: String) -> Result<(), String> {
    let root = state.root.lock().unwrap().clone().ok_or("no root set")?;
    let p = PathBuf::from(&path);
    if !p.starts_with(&root) {
        return Err("path outside library root".into());
    }
    fs::write(&p, contents).map_err(|e| e.to_string())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            set_root,
            get_root,
            list_tree,
            read_text_file,
            write_text_file
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
