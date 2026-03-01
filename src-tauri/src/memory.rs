use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::error::AppError;
use crate::ocr::runtime_resource_root;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryEntry {
    pub name: String,
    pub invoice_type: Option<String>,
    pub use_count: u32,
    /// ISO date "YYYY-MM-DD"
    pub last_seen: String,
    /// Alternative names the user has used for this UBN
    pub aliases: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct FuzzyResult {
    pub ubn: String,
    pub entry: MemoryEntry,
    pub score: f32,
}

type MemoryMap = HashMap<String, MemoryEntry>;

// ---------------------------------------------------------------------------
// File I/O + v1→v2 migration
// ---------------------------------------------------------------------------

fn memory_path() -> std::path::PathBuf {
    runtime_resource_root().join("data").join("ubn_memory.json")
}

fn today_str() -> String {
    // chrono is already a dependency
    chrono::Local::now().format("%Y-%m-%d").to_string()
}

/// Read `ubn_memory.json`, transparently migrating v1 (string values) to v2.
pub fn load_memory() -> Result<MemoryMap, AppError> {
    let path = memory_path();
    if !path.exists() {
        return Ok(HashMap::new());
    }
    let raw = std::fs::read_to_string(&path).map_err(|e| AppError::Internal {
        message: format!("Cannot read ubn_memory.json: {e}"),
        code: 9020,
    })?;
    let value: Value = serde_json::from_str(&raw).unwrap_or(Value::Object(Default::default()));
    let obj = match value.as_object() {
        Some(o) => o,
        None => return Ok(HashMap::new()),
    };

    let mut map = MemoryMap::new();
    for (ubn, val) in obj {
        let entry = match val {
            // v1 — plain string
            Value::String(name) => MemoryEntry {
                name: name.clone(),
                invoice_type: None,
                use_count: 1,
                last_seen: today_str(),
                aliases: vec![],
            },
            // v2 — object
            Value::Object(_) => match serde_json::from_value::<MemoryEntry>(val.clone()) {
                Ok(e) => e,
                Err(_) => continue,
            },
            _ => continue,
        };
        map.insert(ubn.clone(), entry);
    }
    Ok(map)
}

fn save_memory(map: &MemoryMap) -> Result<(), AppError> {
    let path = memory_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| AppError::Internal {
            message: format!("Cannot create data dir: {e}"),
            code: 9021,
        })?;
    }
    let json = serde_json::to_string_pretty(map).map_err(|e| AppError::Internal {
        message: e.to_string(),
        code: 9022,
    })?;
    std::fs::write(&path, json).map_err(|e| AppError::Internal {
        message: format!("Cannot write ubn_memory.json: {e}"),
        code: 9023,
    })
}

// ---------------------------------------------------------------------------
// Bigram similarity (character-level Jaccard)
// ---------------------------------------------------------------------------

fn bigrams(s: &str) -> std::collections::HashSet<(char, char)> {
    let chars: Vec<char> = s.chars().collect();
    chars.windows(2).map(|w| (w[0], w[1])).collect()
}

fn bigram_similarity(a: &str, b: &str) -> f32 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    // Exact or substring fast paths
    if a == b {
        return 1.0;
    }
    if a.contains(b) || b.contains(a) {
        return 0.9;
    }
    let ba = bigrams(a);
    let bb = bigrams(b);
    if ba.is_empty() || bb.is_empty() {
        return 0.0;
    }
    let intersection = ba.intersection(&bb).count();
    let union = ba.union(&bb).count();
    intersection as f32 / union as f32
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

/// Save (upsert) a UBN → name mapping.  Increments use_count if entry exists.
/// `invoice_type` is optional; pass null/undefined from frontend if unknown.
#[tauri::command]
pub async fn save_memory_entry(
    ubn: String,
    name: String,
    invoice_type: Option<String>,
) -> Result<(), AppError> {
    if ubn.is_empty() || name.is_empty() {
        return Ok(());
    }
    let mut map = load_memory()?;
    let today = today_str();
    map.entry(ubn)
        .and_modify(|e| {
            // Keep existing name; update count + date
            if e.name != name && !e.aliases.contains(&name) {
                e.aliases.push(name.clone());
            }
            e.name = name.clone();
            e.use_count += 1;
            e.last_seen = today.clone();
            if invoice_type.is_some() {
                e.invoice_type = invoice_type.clone();
            }
        })
        .or_insert_with(|| MemoryEntry {
            name,
            invoice_type,
            use_count: 1,
            last_seen: today,
            aliases: vec![],
        });
    save_memory(&map)
}

/// Look up a single UBN. Returns null if not found.
#[tauri::command]
pub async fn lookup_memory_entry(ubn: String) -> Result<Option<MemoryEntry>, AppError> {
    let map = load_memory()?;
    Ok(map.get(&ubn).cloned())
}

/// Fuzzy-search company names.  Returns up to 5 results with score > 0.25.
#[tauri::command]
pub async fn fuzzy_search_memory(query: String) -> Result<Vec<FuzzyResult>, AppError> {
    if query.trim().is_empty() {
        return Ok(vec![]);
    }
    let q = query.trim().to_lowercase();
    let map = load_memory()?;

    let mut results: Vec<FuzzyResult> = map
        .into_iter()
        .filter_map(|(ubn, entry)| {
            let name_lower = entry.name.to_lowercase();
            // Check name and all aliases
            let best_score = std::iter::once(bigram_similarity(&q, &name_lower))
                .chain(
                    entry
                        .aliases
                        .iter()
                        .map(|a| bigram_similarity(&q, &a.to_lowercase())),
                )
                .fold(0.0_f32, f32::max);

            if best_score > 0.25 {
                Some(FuzzyResult { ubn, entry, score: best_score })
            } else {
                None
            }
        })
        .collect();

    results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
    results.truncate(5);
    Ok(results)
}
