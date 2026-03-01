use std::collections::HashMap;
use std::path::PathBuf;

use parking_lot::RwLock;
use uuid::Uuid;

use crate::models::RowRecord;

#[derive(Default)]
pub struct AppState {
    pub rows: RwLock<HashMap<Uuid, RowRecord>>,
    pub jobs: RwLock<HashMap<Uuid, Vec<Uuid>>>,
    pub app_data_dir: RwLock<Option<PathBuf>>,
}
